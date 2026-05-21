"""审核 admin 视图测试：权限 / 路由分发 / 文件预览白名单。

本 task (F) 仅含权限 + GET 测试；POST 路由分发与 file_view 白名单将在 Task G/H 加。
"""
import io
import zipfile

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from skillshub.storage.api import get_storage, reset_storage
from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()


@pytest.fixture(autouse=True)
def storage_setup(tmp_path, settings):
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()
    yield
    reset_storage()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(
        username="bob", email="bob@example.com", password="pw", is_staff=True
    )


@pytest.fixture
def member(db):
    """登录用户但 is_staff=False。"""
    return User.objects.create_user(
        username="mallory", email="mallory@example.com", password="pw"
    )


@pytest.fixture
def skill(author):
    return Skill.objects.create(name="demo-skill", description="d", created_by=author)


@pytest.fixture
def pending_review_version(skill, author):
    """落一份带 SKILL.md 的真 zip 到 storage，方便文件预览测试。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo-skill/SKILL.md", "---\nname: demo\n---\n# body\n")
        zf.writestr("demo-skill/extra.py", "print('hi')\n")
        zf.writestr("demo-skill/icon.png", b"\x89PNG\x0d\x0a\x1a\x0a")  # 二进制
    file_path = "skills/demo-skill/v1.zip"
    get_storage().save(file_path, buf.getvalue())

    return SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path=file_path,
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_PENDING_REVIEW,
        submitted_by=author,
        violations=[
            {"code": "L2_REGEX_AWS_KEY", "severity": "high", "message": "key", "location": "x.py"}
        ],
    )


@pytest.fixture
def review_url(pending_review_version):
    return reverse(
        "admin:submit_skillversion_review", args=[pending_review_version.id]
    )


@pytest.fixture
def file_url(pending_review_version):
    return reverse(
        "admin:submit_skillversion_file", args=[pending_review_version.id]
    )


# ---------------- 权限 ----------------

def test_review_view_anonymous_redirected(client, review_url):
    resp = client.get(review_url)
    assert resp.status_code == 302
    assert "login" in resp["Location"]


def test_review_view_member_forbidden(client, member, review_url):
    client.force_login(member)
    resp = client.get(review_url)
    # admin_view 装饰会 302 到 login（要求 staff）
    assert resp.status_code == 302
    assert "login" in resp["Location"]


def test_review_view_staff_ok(client, reviewer, review_url, pending_review_version):
    client.force_login(reviewer)
    resp = client.get(review_url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "alice@example.com" in body
    assert "demo-skill" in body
    assert "L2_REGEX_AWS_KEY" in body
    assert "extra.py" in body


# ---------------- POST 分发 ----------------

@pytest.mark.django_db(transaction=True)
def test_post_approve_dispatches_to_service(
    client, reviewer, review_url, pending_review_version
):
    from unittest.mock import patch
    with patch("skillshub.submit.services.send_review_result_email"):
        client.force_login(reviewer)
        resp = client.post(review_url, {"action": "approve", "reason": ""})

    assert resp.status_code == 302
    assert reverse("admin:submit_pendingskillversion_changelist") in resp["Location"]

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PUBLISHED


@pytest.mark.django_db(transaction=True)
def test_post_reject_requires_reason(
    client, reviewer, review_url, pending_review_version
):
    from unittest.mock import patch
    with patch("skillshub.submit.services.send_review_result_email"):
        client.force_login(reviewer)
        resp = client.post(review_url, {"action": "reject", "reason": ""}, follow=True)

    assert resp.status_code == 200
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PENDING_REVIEW
    # messages.error 出现在响应中
    body = resp.content.decode()
    assert "reason" in body.lower() or "理由" in body or "需要" in body


@pytest.mark.django_db(transaction=True)
def test_post_reject_with_reason(
    client, reviewer, review_url, pending_review_version
):
    from unittest.mock import patch
    with patch("skillshub.submit.services.send_review_result_email"):
        client.force_login(reviewer)
        resp = client.post(review_url, {"action": "reject", "reason": "bad"})

    assert resp.status_code == 302
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_REJECTED


@pytest.mark.django_db(transaction=True)
def test_post_request_changes_with_reason(
    client, reviewer, review_url, pending_review_version
):
    from unittest.mock import patch
    with patch("skillshub.submit.services.send_review_result_email"):
        client.force_login(reviewer)
        resp = client.post(review_url, {"action": "request_changes", "reason": "fix"})

    assert resp.status_code == 302
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_CHANGES_REQUESTED


def test_post_unknown_action(client, reviewer, review_url):
    client.force_login(reviewer)
    resp = client.post(review_url, {"action": "frobnicate", "reason": "x"})
    assert resp.status_code == 400


# ---------------- 文件预览白名单 ----------------

def test_file_view_legitimate_path(client, reviewer, file_url):
    client.force_login(reviewer)
    resp = client.get(file_url, {"path": "demo-skill/SKILL.md"})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/html")
    assert "name: demo" in resp.content.decode()


def test_file_view_escapes_html_content(client, reviewer, pending_review_version):
    """XSS 防御：含 <script> 的文件返回时被 HTML-escape。"""
    import io
    import zipfile
    from skillshub.storage.api import get_storage
    from django.urls import reverse

    # 重写 zip：放一个含 <script> 的 .md 文件
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo-skill/SKILL.md", "<script>alert('xss')</script>\nbody")
    get_storage().save(pending_review_version.file_path, buf.getvalue())

    file_url = reverse("admin:submit_skillversion_file", args=[pending_review_version.id])
    client.force_login(reviewer)
    resp = client.get(file_url, {"path": "demo-skill/SKILL.md"})
    assert resp.status_code == 200
    body = resp.content.decode()
    # 必须是 escape 后的字符串，不能是原始 <script>
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_file_view_path_not_in_namelist(client, reviewer, file_url):
    client.force_login(reviewer)
    resp = client.get(file_url, {"path": "demo-skill/nonexistent.md"})
    assert resp.status_code == 400


def test_file_view_suffix_not_whitelisted(client, reviewer, file_url):
    client.force_login(reviewer)
    resp = client.get(file_url, {"path": "demo-skill/icon.png"})
    assert resp.status_code == 400


def test_file_view_path_traversal_attempt_rejected(client, reviewer, file_url):
    client.force_login(reviewer)
    # path 不在 namelist + 后缀 .py 在白名单 → 仍按 namelist 拒
    resp = client.get(file_url, {"path": "../../../etc/passwd.py"})
    assert resp.status_code == 400


def test_file_view_anonymous_redirected(client, file_url):
    resp = client.get(file_url, {"path": "demo-skill/SKILL.md"})
    assert resp.status_code == 302


def test_file_view_missing_path_param(client, reviewer, file_url):
    client.force_login(reviewer)
    resp = client.get(file_url)
    assert resp.status_code == 400
