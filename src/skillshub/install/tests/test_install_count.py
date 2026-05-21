"""install_count 计数 + 异常兜底 测试 (T10)."""
from unittest.mock import patch
import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_published(author, install_count=5):
    skill = Skill.objects.create(name="foo", description="d", created_by=author, install_count=install_count)
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path="skills/foo/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=author, download_token="count-token-xxxxxxxxx",
    )
    skill.latest_version = v
    skill.save()
    return v


def test_install_sh_increments_count(client, author):
    v = _make_published(author, install_count=5)
    client.get(f"/install/{v.download_token}.sh")
    v.skill.refresh_from_db()
    assert v.skill.install_count == 6


def test_install_ps1_increments_count(client, author):
    v = _make_published(author, install_count=5)
    client.get(f"/install/{v.download_token}.ps1")
    v.skill.refresh_from_db()
    assert v.skill.install_count == 6


def test_install_zip_increments_count(client, author):
    v = _make_published(author, install_count=5)
    with patch("skillshub.install.views.get_storage") as mock_get_storage:
        mock_get_storage.return_value.url.return_value = "https://x/y.zip"
        client.get(f"/install/{v.download_token}/zip")
    v.skill.refresh_from_db()
    assert v.skill.install_count == 6


def test_install_count_db_error_does_not_block_response(client, author):
    """install_count update 异常时仍返回脚本 200."""
    v = _make_published(author, install_count=5)
    with patch("skillshub.install.views.Skill.objects.filter") as mock_filter:
        mock_filter.side_effect = Exception("simulated DB error")
        resp = client.get(f"/install/{v.download_token}.sh")
    assert resp.status_code == 200
    assert "SKILL_NAME" in resp.content.decode()
