"""install 视图对 is_listed 闸门的测试。"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_published_skill(name, author, *, is_listed=True):
    skill = Skill.objects.create(
        name=name, description="d", created_by=author, is_listed=is_listed,
    )
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path=f"skills/{name}/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
        download_token="tok-" + name,
    )
    skill.latest_version = v
    skill.save(update_fields=["latest_version"])
    return skill, v


def test_install_sh_listed_skill_200(client, author):
    _make_published_skill("ok", author, is_listed=True)
    resp = client.get(reverse("install_script_sh", args=["tok-ok"]))
    assert resp.status_code == 200


def test_install_sh_delisted_skill_404(client, author):
    _make_published_skill("hidden", author, is_listed=False)
    resp = client.get(reverse("install_script_sh", args=["tok-hidden"]))
    assert resp.status_code == 404


def test_install_zip_delisted_skill_404(client, author):
    _make_published_skill("hidden-zip", author, is_listed=False)
    resp = client.get(reverse("install_zip", args=["tok-hidden-zip"]))
    assert resp.status_code == 404


def test_install_ps1_delisted_skill_404(client, author):
    _make_published_skill("hidden-ps1", author, is_listed=False)
    resp = client.get(
        reverse("install_script_ps1", args=["tok-hidden-ps1"]) + "?os=windows"
    )
    assert resp.status_code == 404


# ---------------- install for disabled version ----------------

def test_install_sh_disabled_version_404(client, author):
    skill, v = _make_published_skill("avail-test", author, is_listed=True)
    v.is_available = False
    v.save(update_fields=["is_available"])
    resp = client.get(reverse("install_script_sh", args=["tok-avail-test"]))
    assert resp.status_code == 404


def test_install_zip_disabled_version_404(client, author):
    skill, v = _make_published_skill("avail-zip", author, is_listed=True)
    v.is_available = False
    v.save(update_fields=["is_available"])
    resp = client.get(reverse("install_zip", args=["tok-avail-zip"]))
    assert resp.status_code == 404
