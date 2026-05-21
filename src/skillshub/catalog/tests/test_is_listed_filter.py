"""catalog 列表 + 详情对 is_listed 闸门的测试。"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def member(db):
    return User.objects.create_user(username="m", email="m@example.com", password="pw")


@pytest.fixture
def staff(db):
    return User.objects.create_user(username="s", email="s@example.com", password="pw", is_staff=True)


def _make_skill(name, author, *, is_listed=True):
    skill = Skill.objects.create(
        name=name, description="d", created_by=author, is_listed=is_listed,
    )
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path=f"x/{name}.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )
    skill.latest_version = v
    skill.save(update_fields=["latest_version"])
    return skill


# ---------------- list 过滤 ----------------

def test_list_view_excludes_delisted(client, author):
    _make_skill("listed", author, is_listed=True)
    _make_skill("delisted", author, is_listed=False)
    resp = client.get(reverse("catalog_list"))
    body = resp.content.decode()
    assert "listed" in body
    assert "delisted" not in body


def test_list_view_includes_after_relisted(client, author):
    s = _make_skill("toggle", author, is_listed=False)
    resp = client.get(reverse("catalog_list"))
    assert "toggle" not in resp.content.decode()

    s.is_listed = True
    s.save(update_fields=["is_listed"])
    resp = client.get(reverse("catalog_list"))
    assert "toggle" in resp.content.decode()


# ---------------- detail 权限矩阵 ----------------

def test_detail_listed_anonymous_ok(client, author):
    _make_skill("ok-listed", author, is_listed=True)
    resp = client.get(reverse("catalog_detail", args=["ok-listed"]))
    assert resp.status_code == 200


def test_detail_delisted_anonymous_404(client, author):
    _make_skill("hidden", author, is_listed=False)
    resp = client.get(reverse("catalog_detail", args=["hidden"]))
    assert resp.status_code == 404


def test_detail_delisted_member_404(client, member, author):
    _make_skill("hidden2", author, is_listed=False)
    client.force_login(member)
    resp = client.get(reverse("catalog_detail", args=["hidden2"]))
    assert resp.status_code == 404


def test_detail_delisted_owner_200(client, author):
    _make_skill("hidden3", author, is_listed=False)
    client.force_login(author)
    resp = client.get(reverse("catalog_detail", args=["hidden3"]))
    assert resp.status_code == 200


def test_detail_delisted_staff_200(client, staff, author):
    _make_skill("hidden4", author, is_listed=False)
    client.force_login(staff)
    resp = client.get(reverse("catalog_detail", args=["hidden4"]))
    assert resp.status_code == 200


# ---------------- detail ?v=<n> 对 disabled version 的处理 ----------------

def _make_version(skill, version_no, author, *, is_available=True):
    v = SkillVersion.objects.create(
        skill=skill, version_no=version_no, file_path=f"x/v{version_no}.zip",
        sha256=str(version_no) * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
        is_available=is_available,
    )
    return v


def test_detail_v_param_disabled_anonymous_404(client, author):
    skill = _make_skill("v-disable", author, is_listed=True)
    v1 = skill.latest_version
    v2 = _make_version(skill, 2, author, is_available=False)
    skill.latest_version = v2
    skill.save(update_fields=["latest_version"])
    # latest_version (v2) is disabled
    resp = client.get(reverse("catalog_detail", args=["v-disable"]))
    assert resp.status_code == 404


def test_detail_v_param_disabled_owner_200(client, author):
    skill = _make_skill("v-disable2", author, is_listed=True)
    _make_version(skill, 2, author, is_available=False)
    client.force_login(author)
    resp = client.get(reverse("catalog_detail", args=["v-disable2"]) + "?v=2")
    assert resp.status_code == 200


def test_detail_v_param_disabled_staff_200(client, staff, author):
    skill = _make_skill("v-disable3", author, is_listed=True)
    _make_version(skill, 2, author, is_available=False)
    client.force_login(staff)
    resp = client.get(reverse("catalog_detail", args=["v-disable3"]) + "?v=2")
    assert resp.status_code == 200
