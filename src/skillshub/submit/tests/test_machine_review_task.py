"""machine_review task 集成测试（DB + Celery EAGER）。"""
from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from skillshub.storage.api import get_storage, reset_storage
from skillshub.submit.machine_review.task import MachineReviewTask, machine_review
from skillshub.submit.models import Skill, SkillVersion


VALID_FM = b"---\nname: my-skill\ndescription: example\n---\nbody"


def make_zip(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def storage_tmp(tmp_path, settings):
    """每个测试使用 tmp_path 作为 storage root，避免写入 /app/data 只读路径。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()
    yield
    reset_storage()


@pytest.fixture
def alice(db):
    User = get_user_model()
    return User.objects.create_user(username="alice", email="alice@e.com", password="x")


def _create_pending(skill_name: str, alice, content: bytes, file_path: str = "skills/x.zip") -> SkillVersion:
    """直接落 storage + 建 pending_machine version；绕过 services.create_skill_version 以隔离 task 测试。"""
    get_storage().save(file_path, content)
    skill = Skill.objects.create(name=skill_name, description="d", created_by=alice)
    version = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path=file_path,
        sha256="x" * 64, readme="r",
        status=SkillVersion.STATUS_PENDING_MACHINE, submitted_by=alice,
    )
    return version


# ─── 主流程 ───
@pytest.mark.django_db
def test_zero_violations_auto_publishes(alice):
    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/zero.zip")
    machine_review(version.id)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PUBLISHED
    assert version.published_at is not None
    assert version.violations == []
    version.skill.refresh_from_db()
    assert version.skill.latest_version_id == version.id
    assert version.machine_review_result["l1_passed"] is True
    assert version.machine_review_result["l2_passed"] is True


@pytest.mark.django_db
def test_l1_violations_routes_to_pending_review(alice):
    bad = make_zip({"my-skill/foo.md": "x"})  # 缺 SKILL.md
    version = _create_pending("my-skill", alice, bad, file_path="skills/l1.zip")
    machine_review(version.id)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert version.violations
    assert any(v["code"].startswith("l1.") for v in version.violations)
    assert version.machine_review_result["l1_passed"] is False


@pytest.mark.django_db
def test_l2_violations_routes_to_pending_review(alice):
    bad_py = "key = 'AKIAIOSFODNN7EXAMPLE'\n"
    content = make_zip({"my-skill/SKILL.md": VALID_FM, "my-skill/c.py": bad_py})
    version = _create_pending("my-skill", alice, content, file_path="skills/l2.zip")
    machine_review(version.id)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert any(v["code"] == "l2.secret.aws_access_key" for v in version.violations)
    assert version.machine_review_result["l2_passed"] is False
    assert version.machine_review_result["l1_passed"] is True


# ─── 状态守卫（幂等）───
@pytest.mark.django_db
def test_machine_review_skips_terminal_state(alice):
    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/term.zip")
    version.status = SkillVersion.STATUS_CANCELLED
    version.save(update_fields=["status"])
    machine_review(version.id)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_CANCELLED
    assert version.violations is None  # task 没动


@pytest.mark.django_db
def test_machine_review_skips_already_published(alice):
    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/pub.zip")
    version.status = SkillVersion.STATUS_PUBLISHED
    version.save(update_fields=["status"])
    machine_review(version.id)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PUBLISHED


@pytest.mark.django_db
def test_machine_review_skips_pending_review(alice):
    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/pr.zip")
    version.status = SkillVersion.STATUS_PENDING_REVIEW
    version.save(update_fields=["status"])
    machine_review(version.id)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert version.violations is None  # task 没动 DB 字段


# ─── 异常兜底 ───
# 按 Celery 官方测试指南（参考 T11 test_tasks.py）：EAGER mode 不适合测 retry；
# 直接 unit-test on_failure hook 函数 — 验证持久化 + status 守卫逻辑。
@pytest.mark.django_db
def test_on_failure_writes_synthetic_violation(alice):
    """on_failure 在 version 仍 pending_machine 时写合成 l1.internal_error violation 并转 pending_review。"""

    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/err.zip")

    task = MachineReviewTask()
    exc = RuntimeError("boom")
    task.on_failure(
        exc=exc, task_id="t-001",
        args=(version.id,),
        kwargs={},
        einfo=None,
    )

    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert len(version.violations) == 1
    assert version.violations[0]["code"] == "l1.internal_error"
    assert version.violations[0]["severity"] == "error"
    assert version.machine_review_result["l1_passed"] is False
    assert version.machine_review_result["l2_passed"] is False
    assert version.machine_review_result["violation_count"]["error"] == 1


@pytest.mark.django_db
def test_on_failure_after_user_cancel_does_not_overwrite(alice):
    """version 已被 cancel 时调 on_failure：.filter(status=pending_machine).update 影响 0 行。"""

    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/race.zip")
    # 模拟作者已 cancel
    SkillVersion.objects.filter(pk=version.id).update(status=SkillVersion.STATUS_CANCELLED)

    task = MachineReviewTask()
    task.on_failure(
        exc=RuntimeError("boom-after-cancel"),
        task_id="t-002",
        args=(version.id,),
        kwargs={},
        einfo=None,
    )

    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_CANCELLED
    # on_failure 不应覆盖 violations
    assert version.violations is None


@pytest.mark.django_db
def test_on_failure_handles_kwargs_form_args(alice):
    """on_failure 兼容 kwargs={'version_id': X} 的传参形式（celery 调度时可能 kwargs 化）。"""

    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/kw.zip")

    task = MachineReviewTask()
    task.on_failure(
        exc=RuntimeError("kw-form"), task_id="t-003",
        args=(),
        kwargs={"version_id": version.id},
        einfo=None,
    )

    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert version.violations[0]["code"] == "l1.internal_error"


# ─── publish_version 放宽路径回归 ───
@pytest.mark.django_db
def test_publish_version_accepts_pending_machine(alice):
    """T7 直接调 publish_version 传入 pending_machine version 应成功。"""
    from skillshub.submit.services import publish_version
    content = make_zip({"my-skill/SKILL.md": VALID_FM})
    version = _create_pending("my-skill", alice, content, file_path="skills/pv.zip")
    assert version.status == SkillVersion.STATUS_PENDING_MACHINE
    publish_version(version)
    version.refresh_from_db()
    assert version.status == SkillVersion.STATUS_PUBLISHED
    assert version.published_at is not None
