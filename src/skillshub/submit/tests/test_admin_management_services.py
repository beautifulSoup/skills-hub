"""delist_skill / relist_skill / rollback_skill service 测试。

覆盖：成功路径 / reason 必填 / 状态守卫 / 跨 skill / 幂等拒。
"""
import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import ReviewAction, Skill, SkillVersion
from skillshub.submit.services import (
    InvalidOperationError,
    InvalidStateError,
    delist_skill,
    relist_skill,
    rollback_skill,
)

User = get_user_model()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="bob", email="bob@example.com", password="pw", is_staff=True
    )


@pytest.fixture
def skill_with_published_v1(author):
    """skill + 一个 published 版本作为 latest_version。"""
    skill = Skill.objects.create(name="demo-skill", description="d", created_by=author)
    v1 = SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path="skills/demo-skill/v1.zip",
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=author,
    )
    skill.latest_version = v1
    skill.save(update_fields=["latest_version"])
    return skill


# ---------------- delist_skill ----------------

def test_delist_happy_path(skill_with_published_v1, admin_user):
    """delist 成功：is_listed False，ReviewAction(delist, version=v1) 写入。"""
    delist_skill(skill_with_published_v1, actor=admin_user, reason="作者要求")

    skill_with_published_v1.refresh_from_db()
    assert skill_with_published_v1.is_listed is False

    actions = list(ReviewAction.objects.filter(version__skill=skill_with_published_v1))
    assert len(actions) == 1
    assert actions[0].action == ReviewAction.ACTION_DELIST
    assert actions[0].actor_id == admin_user.id
    assert actions[0].reason == "作者要求"
    assert actions[0].version_id == skill_with_published_v1.latest_version_id


def test_delist_empty_reason_raises(skill_with_published_v1, admin_user):
    with pytest.raises(ValueError, match="reason"):
        delist_skill(skill_with_published_v1, actor=admin_user, reason="")

    skill_with_published_v1.refresh_from_db()
    assert skill_with_published_v1.is_listed is True
    assert ReviewAction.objects.count() == 0


def test_delist_whitespace_reason_raises(skill_with_published_v1, admin_user):
    with pytest.raises(ValueError):
        delist_skill(skill_with_published_v1, actor=admin_user, reason="   ")

    skill_with_published_v1.refresh_from_db()
    assert skill_with_published_v1.is_listed is True
    assert ReviewAction.objects.count() == 0


def test_delist_no_latest_version_raises(author, admin_user):
    """skill 还没有任何 published 版本 → InvalidOperationError。"""
    skill = Skill.objects.create(name="empty-skill", description="d", created_by=author)
    with pytest.raises(InvalidOperationError, match="latest"):
        delist_skill(skill, actor=admin_user, reason="尝试下线")


def test_delist_already_delisted_raises(skill_with_published_v1, admin_user):
    """已下线 skill 再次 delist → InvalidOperationError，不重复写审计。"""
    delist_skill(skill_with_published_v1, actor=admin_user, reason="一次")
    with pytest.raises(InvalidOperationError, match="已下线"):
        delist_skill(skill_with_published_v1, actor=admin_user, reason="二次")
    assert ReviewAction.objects.filter(
        action=ReviewAction.ACTION_DELIST
    ).count() == 1


# ---------------- relist_skill ----------------

def test_relist_happy_path(skill_with_published_v1, admin_user):
    """先下线再上线：is_listed True→False→True，两条 ReviewAction。"""
    delist_skill(skill_with_published_v1, actor=admin_user, reason="先下")
    relist_skill(skill_with_published_v1, actor=admin_user, reason="再上")

    skill_with_published_v1.refresh_from_db()
    assert skill_with_published_v1.is_listed is True

    actions = list(ReviewAction.objects.filter(
        version__skill=skill_with_published_v1
    ).order_by("created_at"))
    assert [a.action for a in actions] == [
        ReviewAction.ACTION_DELIST,
        ReviewAction.ACTION_RELIST,
    ]
    assert actions[1].reason == "再上"


def test_relist_empty_reason_raises(skill_with_published_v1, admin_user):
    delist_skill(skill_with_published_v1, actor=admin_user, reason="先下")
    with pytest.raises(ValueError):
        relist_skill(skill_with_published_v1, actor=admin_user, reason="")


def test_relist_already_listed_raises(skill_with_published_v1, admin_user):
    """上线状态再 relist → InvalidOperationError。"""
    with pytest.raises(InvalidOperationError, match="已上线"):
        relist_skill(skill_with_published_v1, actor=admin_user, reason="多余")
    assert ReviewAction.objects.count() == 0


def test_relist_no_latest_version_raises(author, admin_user):
    """skill 无 latest_version 时 relist → InvalidOperationError。"""
    skill = Skill.objects.create(
        name="empty-relist", description="d", created_by=author, is_listed=False,
    )
    with pytest.raises(InvalidOperationError, match="latest"):
        relist_skill(skill, actor=admin_user, reason="尝试上线")


# ---------------- rollback_skill ----------------

@pytest.fixture
def skill_with_v1_v2_v3(author):
    """skill + v1/v2/v3 都 published，latest=v3。"""
    skill = Skill.objects.create(name="multi-ver", description="d", created_by=author)
    versions = []
    for i in (1, 2, 3):
        v = SkillVersion.objects.create(
            skill=skill,
            version_no=i,
            file_path=f"x/v{i}.zip",
            sha256=str(i) * 64,
            readme="r",
            status=SkillVersion.STATUS_PUBLISHED,
            submitted_by=author,
        )
        versions.append(v)
    skill.latest_version = versions[-1]  # v3
    skill.save(update_fields=["latest_version"])
    return skill, versions


def test_rollback_happy_path(skill_with_v1_v2_v3, admin_user):
    """latest=v3，回退到 v1：latest_version_id 变 v1.id，写 ReviewAction(rollback, version=v1)。"""
    skill, versions = skill_with_v1_v2_v3
    v1, _v2, _v3 = versions

    rollback_skill(skill, v1, actor=admin_user, reason="v3 含 bug")

    skill.refresh_from_db()
    assert skill.latest_version_id == v1.id

    actions = list(ReviewAction.objects.filter(version__skill=skill))
    assert len(actions) == 1
    assert actions[0].action == ReviewAction.ACTION_ROLLBACK
    assert actions[0].version_id == v1.id
    assert actions[0].reason == "v3 含 bug"


def test_rollback_target_not_published_raises(skill_with_v1_v2_v3, admin_user):
    """target.status != published → InvalidStateError。"""
    skill, versions = skill_with_v1_v2_v3
    v1 = versions[0]
    v1.status = SkillVersion.STATUS_REJECTED
    v1.save(update_fields=["status"])

    with pytest.raises(InvalidStateError, match="published"):
        rollback_skill(skill, v1, actor=admin_user, reason="试试")

    skill.refresh_from_db()
    assert skill.latest_version_id == versions[-1].id


def test_rollback_cross_skill_raises(skill_with_v1_v2_v3, admin_user, author):
    """target 属于另一个 skill → InvalidOperationError。"""
    skill, _ = skill_with_v1_v2_v3
    other_skill = Skill.objects.create(name="other", description="d", created_by=author)
    other_v = SkillVersion.objects.create(
        skill=other_skill, version_no=1, file_path="o/v1.zip",
        sha256="0" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )

    with pytest.raises(InvalidOperationError, match="不属于"):
        rollback_skill(skill, other_v, actor=admin_user, reason="错误目标")


def test_rollback_to_current_latest_raises(skill_with_v1_v2_v3, admin_user):
    """target 已经是 current latest → InvalidOperationError。"""
    skill, versions = skill_with_v1_v2_v3
    v3 = versions[-1]
    with pytest.raises(InvalidOperationError, match="当前"):
        rollback_skill(skill, v3, actor=admin_user, reason="无意义")


def test_rollback_empty_reason_raises(skill_with_v1_v2_v3, admin_user):
    skill, versions = skill_with_v1_v2_v3
    v1 = versions[0]
    with pytest.raises(ValueError):
        rollback_skill(skill, v1, actor=admin_user, reason="")


# ---------------- disable_version / enable_version ----------------

from skillshub.submit.services import disable_version, enable_version


@pytest.fixture
def available_version(author):
    """skill + 1 个 published available 版本。"""
    skill = Skill.objects.create(name="ver-disable", description="d", created_by=author)
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path="x/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )
    skill.latest_version = v
    skill.save(update_fields=["latest_version"])
    return v


def test_disable_version_happy_path(available_version, admin_user):
    disable_version(available_version, actor=admin_user, reason="含敏感信息")

    available_version.refresh_from_db()
    assert available_version.is_available is False

    actions = list(ReviewAction.objects.filter(version=available_version))
    assert len(actions) == 1
    assert actions[0].action == ReviewAction.ACTION_DISABLE_VERSION
    assert actions[0].reason == "含敏感信息"


def test_disable_version_empty_reason_raises(available_version, admin_user):
    with pytest.raises(ValueError):
        disable_version(available_version, actor=admin_user, reason="")
    available_version.refresh_from_db()
    assert available_version.is_available is True


def test_disable_version_already_disabled_raises(available_version, admin_user):
    disable_version(available_version, actor=admin_user, reason="一次")
    with pytest.raises(InvalidOperationError, match="已下线"):
        disable_version(available_version, actor=admin_user, reason="二次")


def test_enable_version_happy_path(available_version, admin_user):
    disable_version(available_version, actor=admin_user, reason="先下")
    enable_version(available_version, actor=admin_user, reason="再上")

    available_version.refresh_from_db()
    assert available_version.is_available is True

    actions = list(ReviewAction.objects.filter(version=available_version).order_by("created_at"))
    assert [a.action for a in actions] == [
        ReviewAction.ACTION_DISABLE_VERSION,
        ReviewAction.ACTION_ENABLE_VERSION,
    ]


def test_enable_version_already_enabled_raises(available_version, admin_user):
    with pytest.raises(InvalidOperationError, match="已上线"):
        enable_version(available_version, actor=admin_user, reason="多余")


# ---------------- #6 下线当前版本自动回退 ----------------

def test_disable_current_version_rolls_back_to_previous(skill_with_v1_v2_v3, admin_user):
    """下线 latest(v3) → latest_version 自动回退到上一个可用 published(v2)。"""
    skill, versions = skill_with_v1_v2_v3
    v1, v2, v3 = versions

    disable_version(v3, actor=admin_user, reason="v3 出问题")

    skill.refresh_from_db()
    assert skill.latest_version_id == v2.id


def test_disable_current_version_skips_unavailable_fallback(skill_with_v1_v2_v3, admin_user):
    """回退跳过已下线版本：v2 已下线时，下线 v3 回退到 v1。"""
    skill, versions = skill_with_v1_v2_v3
    v1, v2, v3 = versions
    disable_version(v2, actor=admin_user, reason="v2 也下线")  # v2 不是 latest，不触发回退

    disable_version(v3, actor=admin_user, reason="v3 出问题")

    skill.refresh_from_db()
    assert skill.latest_version_id == v1.id


def test_disable_only_version_sets_latest_none(available_version, admin_user):
    """唯一版本被下线且它是 latest → latest_version 置 None（catalog 隐藏）。"""
    skill = available_version.skill
    disable_version(available_version, actor=admin_user, reason="唯一版本下线")

    skill.refresh_from_db()
    assert skill.latest_version_id is None
