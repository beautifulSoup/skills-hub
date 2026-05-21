"""8.5 View 测试。"""
import io
import zipfile
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import Skill, SkillVersion
from skillshub.storage.api import reset_storage

User = get_user_model()


def make_test_zip(root_dir: str = "demo-skill") -> bytes:
    """生成含唯一根目录 + 根目录下 SKILL.md 的最小 zip（对齐 L1 spec）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{root_dir}/SKILL.md", "# Skill\n")
    return buf.getvalue()


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture(autouse=True)
def reset_storage_cache():
    reset_storage()
    yield
    reset_storage()


# ── GET /submit/ ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_submit_requires_login(client):
    """未登录访问 /submit/ → redirect 到 /login。"""
    resp = client.get("/submit/")
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


@pytest.mark.django_db
def test_get_submit_renders_form(client, alice):
    """已登录 GET /submit/ → 200 + 表单。"""
    client.force_login(alice)
    resp = client.get("/submit/")
    assert resp.status_code == 200
    assert b"name" in resp.content


# ── POST /submit/ ────────────────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_post_submit_creates_skillversion_and_redirects(client, alice, tmp_path, settings):
    """合法 POST → 创建 Skill + SkillVersion → redirect /submit/?ok=1。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    client.force_login(alice)
    zip_bytes = make_test_zip()

    with patch("skillshub.submit.services.machine_review") as mock_task:
        mock_task.delay = MagicMock()
        resp = client.post(
            "/submit/",
            {
                "name": "test-skill",
                "description": "a test skill",
                "readme": "## Readme\nSome content",
                "tags": "python,test",
                "content": io.BytesIO(zip_bytes),
            },
        )

    assert resp.status_code == 302
    assert "ok=1" in resp["Location"]
    assert Skill.objects.filter(name="test-skill").count() == 1
    assert SkillVersion.objects.filter(skill__name="test-skill").count() == 1


@pytest.mark.django_db
def test_post_submit_invalid_name_rerenders_form(client, alice):
    """非法 name（含空格）→ 重新渲染表单，DB 不变。"""
    client.force_login(alice)
    resp = client.post(
        "/submit/",
        {
            "name": "AB cd",
            "description": "desc",
            "readme": "readme",
            "tags": "",
            "content": io.BytesIO(make_test_zip()),
        },
    )
    assert resp.status_code == 200
    assert Skill.objects.count() == 0


# ── POST /skills/<skill_id>/versions/<version_id>/cancel ─────────────────────


@pytest.mark.django_db(transaction=True)
def test_cancel_view_marks_status_cancelled(client, alice, tmp_path, settings):
    """作者 POST cancel → version.status = cancelled → redirect /submit/?cancelled=1。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    skill = Skill.objects.create(name="cancel-skill", description="d", created_by=alice)
    version = SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/cancel-skill/v1.zip",
        sha256="a" * 64,
        readme="readme",
        status=SkillVersion.STATUS_PENDING_MACHINE,
        submitted_by=alice,
    )

    client.force_login(alice)
    resp = client.post(f"/skills/{skill.pk}/versions/{version.pk}/cancel")

    assert resp.status_code == 302
    assert "cancelled=1" in resp["Location"]
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_CANCELLED


@pytest.mark.django_db
def test_get_submit_with_skill_param_locks_name_field(client, alice):
    """GET /submit/?skill=foo → name 字段 disabled + initial=foo。"""
    Skill.objects.create(name="foo", description="d", created_by=alice)
    client.force_login(alice)
    resp = client.get("/submit/?skill=foo")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Django form 的 disabled 字段渲染为 <input disabled>
    assert "disabled" in body
    # initial value 落到 input value 里
    assert 'value="foo"' in body
    # help text 提示
    assert "不能修改" in body


@pytest.mark.django_db(transaction=True)
def test_post_submit_with_skill_param_ignores_user_tampered_name(
    client, alice, tmp_path, settings,
):
    """POST /submit/?skill=foo 时即使 form data 里 name=bar，也按 lock_name=foo 提交。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    skill = Skill.objects.create(name="foo", description="d", created_by=alice)
    SkillVersion.objects.create(
        skill=skill, version_no=1, file_path="x/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_REJECTED, submitted_by=alice,
    )
    client.force_login(alice)
    zip_bytes = make_test_zip()
    with patch("skillshub.submit.services.machine_review") as mock_task:
        mock_task.delay = MagicMock()
        resp = client.post(
            "/submit/?skill=foo",
            {
                "name": "bar",  # 用户绕过前端篡改
                "description": "v2 desc",
                "readme": "## v2",
                "tags": "",
                "content": io.BytesIO(zip_bytes),
            },
        )

    assert resp.status_code == 302
    # 不应创建 bar，而是给 foo 增 v2
    assert not Skill.objects.filter(name="bar").exists()
    assert SkillVersion.objects.filter(skill__name="foo").count() == 2
    assert SkillVersion.objects.filter(skill__name="foo", version_no=2).exists()


@pytest.mark.django_db
def test_cancel_view_skill_id_mismatch_returns_404(client, alice):
    """URL skill_id 与 version 所属 skill 不匹配 → 404。"""
    skill_a = Skill.objects.create(name="skill-a", description="d", created_by=alice)
    skill_b = Skill.objects.create(name="skill-b", description="d", created_by=alice)
    version = SkillVersion.objects.create(
        skill=skill_a,
        version_no=1,
        file_path="skills/skill-a/v1.zip",
        sha256="a" * 64,
        readme="readme",
        status=SkillVersion.STATUS_PENDING_MACHINE,
        submitted_by=alice,
    )

    client.force_login(alice)
    # skill_b.pk 与 version 所属 skill_a.pk 不匹配
    resp = client.post(f"/skills/{skill_b.pk}/versions/{version.pk}/cancel")
    assert resp.status_code == 404
