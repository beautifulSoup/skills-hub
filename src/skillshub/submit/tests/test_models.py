"""8.2 数据模型测试。"""
import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def skill(user):
    return Skill.objects.create(name="code-reviewer-zh", description="desc", created_by=user)


# ── Skill 测试 ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_skill_unique_name(skill):
    """同名 Skill 创建失败（unique constraint）。"""
    other_user = User.objects.create_user(username="bob", email="bob@example.com", password="pw")
    with pytest.raises(IntegrityError):
        Skill.objects.create(name="code-reviewer-zh", description="other", created_by=other_user)


@pytest.mark.django_db
def test_skill_defaults(user):
    """未指定 type / tags / install_count 时使用默认值。"""
    s = Skill.objects.create(name="my-skill", description="d", created_by=user)
    assert s.type == "skill"
    assert s.tags == []
    assert s.install_count == 0
    assert s.latest_version_id is None
    assert s.is_listed is True


# ── SkillVersion 测试 ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_status_choices_enum():
    """STATUS_CHOICES 含且仅含 6 个状态值。"""
    status_values = {key for key, _ in SkillVersion.STATUS_CHOICES}
    assert status_values == {
        "pending_machine",
        "pending_review",
        "changes_requested",
        "published",
        "rejected",
        "cancelled",
    }


@pytest.mark.django_db
def test_terminal_non_terminal_sets():
    """TERMINAL 和 NON_TERMINAL 集合不重叠、合集等于全部状态。"""
    all_statuses = {key for key, _ in SkillVersion.STATUS_CHOICES}
    assert SkillVersion.TERMINAL_STATUSES | SkillVersion.NON_TERMINAL_STATUSES == all_statuses
    assert SkillVersion.TERMINAL_STATUSES & SkillVersion.NON_TERMINAL_STATUSES == set()


@pytest.mark.django_db
def test_skillversion_unique_per_skill_version_no(skill, user):
    """同 skill 相同 version_no 唯一约束。"""
    SkillVersion.objects.create(
        skill=skill,
        version_no=2,
        file_path="skills/code-reviewer-zh/v2.zip",
        sha256="a" * 64,
        readme="readme",
        status="pending_machine",
        submitted_by=user,
    )
    with pytest.raises(IntegrityError):
        SkillVersion.objects.create(
            skill=skill,
            version_no=2,
            file_path="skills/code-reviewer-zh/v2.zip",
            sha256="b" * 64,
            readme="readme2",
            status="pending_machine",
            submitted_by=user,
        )


# ── T6 新增测试 ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_skill_latest_version_int_access_compat():
    """T6 重命名后 skill.latest_version_id 仍返回 int/None（向后兼容 T5 测试）。"""
    u = User.objects.create_user(username="u_lv1", email="u_lv1@e.com", password="x")
    s = Skill.objects.create(name="s_lv1", description="d", created_by=u)
    assert s.latest_version_id is None
    assert s.latest_version is None


@pytest.mark.django_db
def test_skill_latest_version_set_null_on_version_delete():
    """admin 强删 latest version 后，Skill 行 latest_version_id 变 NULL，Skill 不被连带删。"""
    u = User.objects.create_user(username="u_lv2", email="u_lv2@e.com", password="x")
    s = Skill.objects.create(name="s_lv2", description="d", created_by=u)
    v = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PUBLISHED, submitted_by=u,
    )
    s.latest_version = v
    s.save()
    v.delete()
    s.refresh_from_db()
    assert s.latest_version_id is None
    assert Skill.objects.filter(pk=s.pk).exists()


@pytest.mark.django_db
def test_skillversion_published_at_default_null():
    u = User.objects.create_user(username="u_lv3", email="u_lv3@e.com", password="x")
    s = Skill.objects.create(name="s_lv3", description="d", created_by=u)
    v = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p", sha256="x" * 64,
        readme="r", submitted_by=u,
    )
    assert v.published_at is None


@pytest.mark.django_db(transaction=True)
def test_in_flight_unique_constraint_blocks_second_non_terminal():
    """DB 层 generated column unique index 拒绝同 skill 第二条非终结 version。"""
    if connection.vendor != "mysql":
        pytest.skip("partial unique via generated column 仅在 MySQL 测")
    u = User.objects.create_user(username="u_lv4", email="u_lv4@e.com", password="x")
    s = Skill.objects.create(name="s_lv4", description="d", created_by=u)
    SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p1", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_MACHINE, submitted_by=u,
    )
    with pytest.raises(IntegrityError):
        SkillVersion.objects.create(
            skill=s, version_no=2, file_path="p2", sha256="y" * 64,
            readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
        )


@pytest.mark.django_db
def test_in_flight_constraint_releases_on_terminal():
    """非终结转终结后，generated column 变 NULL，同 skill 可再插非终结版本。"""
    u = User.objects.create_user(username="u_lv5", email="u_lv5@e.com", password="x")
    s = Skill.objects.create(name="s_lv5", description="d", created_by=u)
    v1 = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p1", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_MACHINE, submitted_by=u,
    )
    v1.status = SkillVersion.STATUS_CANCELLED
    v1.save()
    # 不应 raise
    SkillVersion.objects.create(
        skill=s, version_no=2, file_path="p2", sha256="y" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_MACHINE, submitted_by=u,
    )
