"""approve_version / reject_version / request_changes_version service 测试。

覆盖：成功路径 / 状态守卫 / reason 校验 / ReviewAction 写入 /
邮件入队 1 次 / 邮件失败不回滚状态。
"""
import pytest
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model

from skillshub.submit.models import ReviewAction, Skill, SkillVersion
from skillshub.submit.services import (
    InvalidStateError,
    approve_version,
    reject_version,
    request_changes_version,
)

User = get_user_model()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(
        username="bob", email="bob@example.com", password="pw", is_staff=True
    )


@pytest.fixture
def skill(author):
    return Skill.objects.create(name="demo-skill", description="d", created_by=author)


@pytest.fixture
def pending_review_version(skill, author):
    return SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/demo-skill/v1.zip",
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_PENDING_REVIEW,
        submitted_by=author,
    )


# ---------------- approve ----------------

def test_approve_happy_path(pending_review_version, reviewer):
    """approve 成功：状态变 published / latest_version 指向 / ReviewAction 写入 / 邮件入队 1 次。"""
    mock_email = MagicMock()
    with patch("skillshub.submit.services.send_review_result_email", mock_email):
        approve_version(pending_review_version, actor=reviewer)

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PUBLISHED
    assert pending_review_version.published_at is not None

    skill = pending_review_version.skill
    skill.refresh_from_db()
    assert skill.latest_version_id == pending_review_version.id

    actions = list(ReviewAction.objects.filter(version=pending_review_version))
    assert len(actions) == 1
    assert actions[0].action == ReviewAction.ACTION_APPROVE
    assert actions[0].actor_id == reviewer.id
    assert actions[0].reason == ""

    assert mock_email.call_count == 1
    kwargs = mock_email.call_args.kwargs
    assert kwargs["to"] == "alice@example.com"
    assert kwargs["decision"] == "approve"
    assert kwargs["skill_name"] == "demo-skill"
    assert kwargs["version_no"] == 1


def test_approve_state_guard(pending_review_version, reviewer):
    """非 pending_review 状态 → InvalidStateError，状态/审计/邮件全不动。"""
    pending_review_version.status = SkillVersion.STATUS_PUBLISHED
    pending_review_version.save(update_fields=["status"])

    mock_email = MagicMock()
    with patch("skillshub.submit.services.send_review_result_email", mock_email):
        with pytest.raises(InvalidStateError):
            approve_version(pending_review_version, actor=reviewer)

    assert ReviewAction.objects.filter(version=pending_review_version).count() == 0
    assert mock_email.call_count == 0


def test_approve_email_failure_does_not_rollback(pending_review_version, reviewer):
    """邮件入队抛异常 → 状态/审计已写入，异常被吞 + warning。"""
    with patch(
        "skillshub.submit.services.send_review_result_email",
        side_effect=RuntimeError("broker down"),
    ):
        approve_version(pending_review_version, actor=reviewer)

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PUBLISHED
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 1


@pytest.fixture
def patch_email():
    with patch("skillshub.submit.services.send_review_result_email") as mock:
        yield mock


# ---------------- reject ----------------

def test_reject_happy_path(pending_review_version, reviewer, patch_email):
    reject_version(pending_review_version, actor=reviewer, reason="contains secret")

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_REJECTED

    actions = list(ReviewAction.objects.filter(version=pending_review_version))
    assert len(actions) == 1
    assert actions[0].action == ReviewAction.ACTION_REJECT
    assert actions[0].reason == "contains secret"
    assert actions[0].actor_id == reviewer.id

    assert patch_email.call_count == 1
    kwargs = patch_email.call_args.kwargs
    assert kwargs["decision"] == "reject"
    assert kwargs["reason"] == "contains secret"


def test_reject_empty_reason_raises(pending_review_version, reviewer, patch_email):
    with pytest.raises(ValueError, match="reason"):
        reject_version(pending_review_version, actor=reviewer, reason="")

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 0
    assert patch_email.call_count == 0


def test_reject_whitespace_reason_raises(pending_review_version, reviewer, patch_email):
    with pytest.raises(ValueError, match="reason"):
        reject_version(pending_review_version, actor=reviewer, reason="   ")
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 0
    assert patch_email.call_count == 0


def test_reject_state_guard(pending_review_version, reviewer, patch_email):
    pending_review_version.status = SkillVersion.STATUS_CHANGES_REQUESTED
    pending_review_version.save(update_fields=["status"])

    with pytest.raises(InvalidStateError):
        reject_version(pending_review_version, actor=reviewer, reason="late")

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_CHANGES_REQUESTED
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 0
    assert patch_email.call_count == 0


def test_reject_email_failure_does_not_rollback(pending_review_version, reviewer):
    """邮件入队抛异常 → 状态/审计已写入，异常被吞 + log.error。"""
    from unittest.mock import patch

    with patch(
        "skillshub.submit.services.send_review_result_email",
        side_effect=RuntimeError("broker down"),
    ):
        reject_version(pending_review_version, actor=reviewer, reason="bad")

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_REJECTED
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 1


# ---------------- request_changes ----------------

def test_request_changes_happy_path(pending_review_version, reviewer, patch_email):
    request_changes_version(pending_review_version, actor=reviewer, reason="add tests")

    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_CHANGES_REQUESTED

    actions = list(ReviewAction.objects.filter(version=pending_review_version))
    assert len(actions) == 1
    assert actions[0].action == ReviewAction.ACTION_REQUEST_CHANGES
    assert actions[0].reason == "add tests"
    assert actions[0].actor_id == reviewer.id

    assert patch_email.call_count == 1
    assert patch_email.call_args.kwargs["decision"] == "changes_requested"
    assert patch_email.call_args.kwargs["reason"] == "add tests"


def test_request_changes_empty_reason_raises(pending_review_version, reviewer, patch_email):
    with pytest.raises(ValueError, match="reason"):
        request_changes_version(pending_review_version, actor=reviewer, reason="")
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 0
    assert patch_email.call_count == 0


def test_request_changes_whitespace_reason_raises(pending_review_version, reviewer, patch_email):
    with pytest.raises(ValueError, match="reason"):
        request_changes_version(pending_review_version, actor=reviewer, reason="   ")
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_PENDING_REVIEW
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 0
    assert patch_email.call_count == 0


def test_request_changes_state_guard(pending_review_version, reviewer, patch_email):
    pending_review_version.status = SkillVersion.STATUS_REJECTED
    pending_review_version.save(update_fields=["status"])
    with pytest.raises(InvalidStateError):
        request_changes_version(pending_review_version, actor=reviewer, reason="x")
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_REJECTED
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 0
    assert patch_email.call_count == 0


def test_request_changes_email_failure_does_not_rollback(pending_review_version, reviewer):
    """邮件入队抛异常 → 状态/审计已写入。"""
    from unittest.mock import patch
    with patch(
        "skillshub.submit.services.send_review_result_email",
        side_effect=RuntimeError("broker down"),
    ):
        request_changes_version(pending_review_version, actor=reviewer, reason="needs work")
    pending_review_version.refresh_from_db()
    assert pending_review_version.status == SkillVersion.STATUS_CHANGES_REQUESTED
    assert ReviewAction.objects.filter(version=pending_review_version).count() == 1


# ---------------- 邮件 e2e（不 patch，走真链路）----------------

def test_approve_sends_real_email_eager(pending_review_version, reviewer, settings):
    """CELERY_EAGER + locmem backend：approve 后 outbox 真出现一封。"""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    from django.core import mail
    mail.outbox = []

    approve_version(pending_review_version, actor=reviewer)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["alice@example.com"]
    assert "demo-skill" in msg.subject or "demo-skill" in msg.body
