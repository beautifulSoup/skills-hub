"""ReviewAction 模型基础测试（建表 + 字段 + PROTECT + index）。"""
import pytest
from django.contrib.auth import get_user_model
from django.db import models

from skillshub.submit.models import ReviewAction, Skill, SkillVersion

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(
        username="bob", email="bob@example.com", password="pw", is_staff=True
    )


@pytest.fixture
def skill(user):
    return Skill.objects.create(name="demo-skill", description="d", created_by=user)


@pytest.fixture
def version(skill, user):
    return SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/demo-skill/v1.zip",
        sha256="0" * 64,
        readme="readme",
        submitted_by=user,
    )


def test_review_action_choices_complete():
    """10 个动作枚举值必须齐全。"""
    expected = {
        "approve",
        "reject",
        "request_changes",
        "cancel_by_author",
        "auto_cancel_by_resubmit",
        "delist",
        "relist",
        "rollback",
        "disable_version",
        "enable_version",
    }
    actual = {choice[0] for choice in ReviewAction.ACTION_CHOICES}
    assert actual == expected


def test_review_action_create_minimal(version, reviewer):
    """空 reason approve 可创建。"""
    ra = ReviewAction.objects.create(
        version=version, actor=reviewer, action=ReviewAction.ACTION_APPROVE
    )
    assert ra.pk
    assert ra.reason == ""
    assert ra.created_at is not None


def test_review_action_protect_on_version_delete(version, reviewer):
    """删 version 必须被 PROTECT 拦住（审计不可级联删）。"""
    ReviewAction.objects.create(
        version=version, actor=reviewer, action=ReviewAction.ACTION_APPROVE
    )
    with pytest.raises(models.ProtectedError):
        version.delete()


def test_review_action_protect_on_actor_delete(version, reviewer):
    """删 actor user 必须被 PROTECT 拦住。"""
    ReviewAction.objects.create(
        version=version, actor=reviewer, action=ReviewAction.ACTION_APPROVE
    )
    with pytest.raises(models.ProtectedError):
        reviewer.delete()


def test_review_action_default_ordering(version, reviewer):
    """Meta.ordering = -created_at；最新动作排第一。"""
    from freezegun import freeze_time

    with freeze_time("2026-01-01 00:00:00"):
        a = ReviewAction.objects.create(
            version=version, actor=reviewer,
            action=ReviewAction.ACTION_REQUEST_CHANGES, reason="r",
        )
    with freeze_time("2026-01-01 00:00:01"):
        b = ReviewAction.objects.create(
            version=version, actor=reviewer, action=ReviewAction.ACTION_APPROVE,
        )
    actions = list(ReviewAction.objects.all())
    assert actions[0].pk == b.pk
    assert actions[1].pk == a.pk
