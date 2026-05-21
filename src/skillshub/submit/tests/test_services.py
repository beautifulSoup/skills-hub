"""8.4 服务层测试（含并发约束、cancel 逻辑）。"""
import io
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from skillshub.submit.models import Skill, SkillVersion
from skillshub.submit.services import (
    ConcurrentSubmissionError,
    InvalidStateError,
    SkillNameConflictError,
    cancel_version,
    create_skill_version,
    latest_published,
    publish_version,
    published_versions,
)
from skillshub.storage.api import reset_storage

User = get_user_model()


# ── Fixtures ─────────────────────────────────────────────────────────────────


def make_test_zip(root_dir: str = "demo-skill", skill_md_present: bool = True) -> bytes:
    """生成含唯一根目录 + 根目录下 SKILL.md 的最小 zip bytes（对齐 L1 spec）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if skill_md_present:
            zf.writestr(f"{root_dir}/SKILL.md", "# Skill\n")
        else:
            zf.writestr(f"{root_dir}/README.md", "no skill md")
    return buf.getvalue()


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def bob(db):
    return User.objects.create_user(username="bob", email="bob@example.com", password="pw")


@pytest.fixture(autouse=True)
def reset_storage_cache():
    """每个测试前后重置 storage 单例，避免 LocalStorage._root 缓存污染。"""
    reset_storage()
    yield
    reset_storage()


# ── create_skill_version ─────────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_create_first_time_creates_skill_and_v1(alice, tmp_path, settings):
    """首次提交 → Skill 新建 + SkillVersion v1 (pending_machine)。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    with patch("skillshub.submit.services.machine_review") as mock_task:
        mock_task.delay = MagicMock()
        version = create_skill_version(
            submitter=alice,
            name="my-skill",
            description="desc",
            readme="readme",
            tags=["python"],
            content_bytes=make_test_zip(),
        )

    assert Skill.objects.filter(name="my-skill").count() == 1
    assert version.version_no == 1
    assert version.status == SkillVersion.STATUS_PENDING_MACHINE
    assert (tmp_path / "skills" / "my-skill" / "v1.zip").exists()


def test_create_duplicate_name_by_other_user_raises(alice, bob, tmp_path, settings):
    """他人提交已存在同名 → SkillNameConflictError，不创建新版本（#8）。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()
    Skill.objects.create(name="taken", description="d", tags=[], created_by=alice)

    with patch("skillshub.submit.services.machine_review") as mock_task:
        mock_task.delay = MagicMock()
        with pytest.raises(SkillNameConflictError, match="已被他人占用"):
            create_skill_version(
                submitter=bob,
                name="taken",
                description="desc",
                readme="readme",
                tags=[],
                content_bytes=make_test_zip(),
            )

    assert SkillVersion.objects.filter(skill__name="taken").count() == 0


@pytest.mark.django_db(transaction=True)
def test_create_existing_skill_increments_version_no(alice, tmp_path, settings):
    """已有 published v1 → 新提交创建 v2。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    skill = Skill.objects.create(name="my-skill", description="d", created_by=alice)
    SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/my-skill/v1.zip",
        sha256="a" * 64,
        readme="readme",
        status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=alice,
    )

    with patch("skillshub.submit.services.machine_review") as mock_task:
        mock_task.delay = MagicMock()
        version = create_skill_version(
            submitter=alice,
            name="my-skill",
            description="desc",
            readme="readme v2",
            tags=[],
            content_bytes=make_test_zip(),
        )

    assert version.version_no == 2
    assert Skill.objects.filter(name="my-skill").count() == 1


@pytest.mark.django_db(transaction=True)
def test_resubmit_syncs_description_and_tags_to_skill(alice, tmp_path, settings):
    """v2 提交时填的新 description/tags 必须同步到 Skill 表（旧 bug：被 defaults 忽略）。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    skill = Skill.objects.create(
        name="my-skill", description="old-desc", tags=[], created_by=alice,
    )
    SkillVersion.objects.create(
        skill=skill, version_no=1, file_path="skills/my-skill/v1.zip",
        sha256="a" * 64, readme="r", status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=alice,
    )

    with patch("skillshub.submit.services.machine_review") as mock_task:
        mock_task.delay = MagicMock()
        create_skill_version(
            submitter=alice,
            name="my-skill",
            description="new-desc",
            readme="readme v2",
            tags=["python", "review"],
            content_bytes=make_test_zip(),
        )

    skill.refresh_from_db()
    assert skill.description == "new-desc"
    assert skill.tags == ["python", "review"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_submission_blocked_by_pending_version(alice, tmp_path, settings):
    """已有 pending_machine 版本 → 再次提交 raise ConcurrentSubmissionError。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    skill = Skill.objects.create(name="my-skill", description="d", created_by=alice)
    SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/my-skill/v1.zip",
        sha256="a" * 64,
        readme="readme",
        status=SkillVersion.STATUS_PENDING_MACHINE,
        submitted_by=alice,
    )

    with pytest.raises(ConcurrentSubmissionError):
        create_skill_version(
            submitter=alice,
            name="my-skill",
            description="desc",
            readme="readme",
            tags=[],
            content_bytes=make_test_zip(),
        )

    # DB 未变
    assert SkillVersion.objects.filter(skill=skill).count() == 1


@pytest.mark.django_db(transaction=True)
def test_invalid_zip_raises_validationerror(alice, tmp_path, settings):
    """非法 zip → ValidationError；DB + storage 不变。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    with pytest.raises(ValidationError):
        create_skill_version(
            submitter=alice,
            name="bad-skill",
            description="desc",
            readme="readme",
            tags=[],
            content_bytes=b"not a zip",
        )

    assert Skill.objects.filter(name="bad-skill").count() == 0


@pytest.mark.django_db(transaction=True)
def test_storage_save_called_with_correct_path(alice, tmp_path, settings):
    """file_path 按约定 skills/<name>/v<no>.zip 落 storage。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    with patch("skillshub.submit.services.machine_review") as mock_task:
        mock_task.delay = MagicMock()
        version = create_skill_version(
            submitter=alice,
            name="path-test",
            description="desc",
            readme="readme",
            tags=[],
            content_bytes=make_test_zip(),
        )

    assert version.file_path == "skills/path-test/v1.zip"
    assert (tmp_path / "skills" / "path-test" / "v1.zip").exists()


@pytest.mark.django_db(transaction=True)
def test_machine_review_task_enqueued_after_commit(alice, tmp_path, settings):
    """transaction.on_commit 后 machine_review.delay 被调用一次，参数为 version.id。

    注意：services.py 用 `from tasks import machine_review` 绑定到模块命名空间，
    所以要 patch services 模块里的那个名字，不是 tasks 模块里的。
    """
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    with patch("skillshub.submit.services.machine_review") as mock_task:
        delay_calls = []
        mock_task.delay = lambda version_id: delay_calls.append(version_id)

        version = create_skill_version(
            submitter=alice,
            name="task-test",
            description="desc",
            readme="readme",
            tags=[],
            content_bytes=make_test_zip(),
        )

    # transaction=True 模式：on_commit 在事务 commit 后立即执行
    assert len(delay_calls) == 1
    assert delay_calls[0] == version.id


# ── cancel_version ───────────────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_cancel_version_by_author_works(alice, tmp_path, settings):
    """作者 cancel 自己的 pending_machine 版本 → status = cancelled。"""
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

    cancel_version(alice, version)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_CANCELLED


@pytest.mark.django_db(transaction=True)
def test_cancel_version_by_non_author_raises_permission_denied(alice, bob, tmp_path, settings):
    """非作者 cancel → PermissionDenied。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    skill = Skill.objects.create(name="perm-skill", description="d", created_by=alice)
    version = SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/perm-skill/v1.zip",
        sha256="a" * 64,
        readme="readme",
        status=SkillVersion.STATUS_PENDING_MACHINE,
        submitted_by=alice,
    )

    with pytest.raises(PermissionDenied):
        cancel_version(bob, version)

    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PENDING_MACHINE


@pytest.mark.django_db(transaction=True)
def test_cancel_terminal_version_raises_valueerror(alice, tmp_path, settings):
    """cancel 已终结版本（published）→ ValueError。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()

    skill = Skill.objects.create(name="terminal-skill", description="d", created_by=alice)
    version = SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/terminal-skill/v1.zip",
        sha256="a" * 64,
        readme="readme",
        status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=alice,
    )

    with pytest.raises(ValueError, match="终结"):
        cancel_version(alice, version)


# ── T6 新增：publish_version / published_versions / latest_published ─────────


@pytest.mark.django_db
def test_publish_version_success_sets_all_fields():
    u = User.objects.create_user(username="pu1", email="pu1@e.com", password="x")
    s = Skill.objects.create(name="ps1", description="d", created_by=u)
    v = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
    )
    before = timezone.now()
    publish_version(v)
    v.refresh_from_db()
    s.refresh_from_db()
    assert v.status == SkillVersion.STATUS_PUBLISHED
    assert v.published_at is not None and v.published_at >= before
    assert s.latest_version_id == v.id


@pytest.mark.django_db
def test_publish_version_accepts_pending_machine():
    """T7 放宽：publish_version 接受 pending_machine 入口（机审零违规自动发布路径）。"""
    u = User.objects.create_user(username="pm1", email="pm1@e.com", password="x")
    s = Skill.objects.create(name="pm-skill", description="d", created_by=u)
    v = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_MACHINE, submitted_by=u,
    )
    publish_version(v)
    v.refresh_from_db()
    s.refresh_from_db()
    assert v.status == SkillVersion.STATUS_PUBLISHED
    assert v.published_at is not None
    assert s.latest_version_id == v.id


@pytest.mark.django_db
@pytest.mark.parametrize("bad_status", [
    SkillVersion.STATUS_CHANGES_REQUESTED,
    SkillVersion.STATUS_PUBLISHED,
    SkillVersion.STATUS_REJECTED,
    SkillVersion.STATUS_CANCELLED,
])
def test_publish_version_rejects_other_statuses(bad_status):
    """放宽后仍拒绝四种非 publishable 状态（changes_requested / published / rejected / cancelled）。"""
    u = User.objects.create_user(username=f"r{bad_status[:5]}", email=f"r{bad_status[:5]}@e.com", password="x")
    s = Skill.objects.create(name=f"r-{bad_status}", description="d", created_by=u)
    v = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p", sha256="x" * 64,
        readme="r", status=bad_status, submitted_by=u,
    )
    with pytest.raises(InvalidStateError):
        publish_version(v)


@pytest.mark.django_db
def test_publish_version_overrides_latest():
    """新版本 publish 后，Skill.latest_version 指向新版本（旧 published 版本仍 published）。"""
    u = User.objects.create_user(username="pu3", email="pu3@e.com", password="x")
    s = Skill.objects.create(name="ps3", description="d", created_by=u)
    v1 = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p1", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
    )
    publish_version(v1)
    v2 = SkillVersion.objects.create(
        skill=s, version_no=2, file_path="p2", sha256="y" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
    )
    publish_version(v2)
    s.refresh_from_db()
    v1.refresh_from_db()
    assert s.latest_version_id == v2.id
    assert v1.status == SkillVersion.STATUS_PUBLISHED  # v1 保留


@pytest.mark.django_db
def test_published_versions_returns_only_published_desc():
    u = User.objects.create_user(username="pv1", email="pv1@e.com", password="x")
    s = Skill.objects.create(name="pv1s", description="d", created_by=u)
    for no, status in [(1, "published"), (2, "pending_review"), (3, "published")]:
        SkillVersion.objects.create(
            skill=s, version_no=no, file_path=f"p{no}", sha256="x" * 64,
            readme="r", status=status, submitted_by=u,
        )
    result = list(published_versions(s).values_list("version_no", flat=True))
    assert result == [3, 1]


@pytest.mark.django_db
def test_latest_published_returns_skill_latest_version():
    u = User.objects.create_user(username="lp1", email="lp1@e.com", password="x")
    s = Skill.objects.create(name="lp1s", description="d", created_by=u)
    assert latest_published(s) is None
    v = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
    )
    publish_version(v)
    s.refresh_from_db()
    assert latest_published(s).id == v.id
