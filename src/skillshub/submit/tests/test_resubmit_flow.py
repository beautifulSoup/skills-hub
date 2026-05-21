"""复提流程测试：基于 changes_requested 自动 cancel；其它非终结状态仍拒绝。"""
import io
import zipfile
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import ReviewAction, Skill, SkillVersion
from skillshub.submit.services import (
    ConcurrentSubmissionError,
    create_skill_version,
)
from skillshub.storage.api import reset_storage

User = get_user_model()


@pytest.fixture(autouse=True)
def storage_setup(tmp_path, settings):
    """为每个测试设置可写的本地 storage 根目录。"""
    settings.STORAGE_LOCAL_ROOT = str(tmp_path)
    reset_storage()
    yield
    reset_storage()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_zip(skill_name: str = "demo-skill") -> bytes:
    """生成 zip：唯一根目录 <skill_name>/ + 根目录下 SKILL.md（对齐 L1 spec）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{skill_name}/SKILL.md",
            f"---\nname: {skill_name}\ndescription: demo\n---\n# body\n",
        )
    return buf.getvalue()


@pytest.fixture
def skill_with_changes_requested(author):
    """已有 changes_requested 旧版的 skill（模拟 admin 已 request_changes 过）。"""
    skill = Skill.objects.create(name="demo-skill", description="d", created_by=author)
    SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/demo-skill/v1.zip",
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_CHANGES_REQUESTED,
        submitted_by=author,
    )
    return skill


@pytest.fixture
def skill_with_pending_review(author):
    skill = Skill.objects.create(name="demo-skill", description="d", created_by=author)
    SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/demo-skill/v1.zip",
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_PENDING_REVIEW,
        submitted_by=author,
    )
    return skill


@pytest.mark.django_db(transaction=True)
def test_resubmit_after_changes_requested_auto_cancels_old(
    skill_with_changes_requested, author
):
    """changes_requested 老版 → 自动 cancel + ReviewAction(auto_cancel) + 新版 pending_machine。"""
    with patch("skillshub.submit.services.machine_review.delay"):  # 阻断真 task
        new_v = create_skill_version(
            submitter=author,
            name="demo-skill",
            description="d",
            readme="r",
            tags=[],
            content_bytes=_make_zip(),
        )

    old_v = SkillVersion.objects.get(version_no=1)
    assert old_v.status == SkillVersion.STATUS_CANCELLED

    auto_cancel_actions = ReviewAction.objects.filter(
        version=old_v, action=ReviewAction.ACTION_AUTO_CANCEL_BY_RESUBMIT
    )
    assert auto_cancel_actions.count() == 1
    assert auto_cancel_actions.first().actor_id == author.id

    assert new_v.status == SkillVersion.STATUS_PENDING_MACHINE
    assert new_v.version_no == 2


@pytest.mark.django_db(transaction=True)
def test_resubmit_pending_review_still_rejected(skill_with_pending_review, author):
    """pending_review 老版仍按 R-3/R-14 拒绝。"""
    with patch("skillshub.submit.services.machine_review.delay"):
        with pytest.raises(ConcurrentSubmissionError):
            create_skill_version(
                submitter=author,
                name="demo-skill",
                description="d",
                readme="r",
                tags=[],
                content_bytes=_make_zip(),
            )

    old_v = SkillVersion.objects.get(version_no=1)
    assert old_v.status == SkillVersion.STATUS_PENDING_REVIEW
    assert SkillVersion.objects.filter(skill=old_v.skill).count() == 1


@pytest.mark.django_db(transaction=True)
def test_resubmit_pending_machine_still_rejected(author):
    """pending_machine 老版仍按 R-3/R-14 拒绝。"""
    skill = Skill.objects.create(name="demo-skill", description="d", created_by=author)
    SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="x",
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_PENDING_MACHINE,
        submitted_by=author,
    )
    with patch("skillshub.submit.services.machine_review.delay"):
        with pytest.raises(ConcurrentSubmissionError):
            create_skill_version(
                submitter=author,
                name="demo-skill",
                description="d",
                readme="r",
                tags=[],
                content_bytes=_make_zip(),
            )

    old_v = SkillVersion.objects.get(version_no=1)
    assert old_v.status == SkillVersion.STATUS_PENDING_MACHINE
    assert SkillVersion.objects.filter(skill=old_v.skill).count() == 1
