"""install_zip_view 测试 (T10)."""
from unittest.mock import patch
import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_published(author, name="foo", token="zip-token-xxxxxxxxxxx"):
    skill = Skill.objects.create(name=name, description="d", created_by=author)
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path=f"skills/{name}/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=author, download_token=token,
    )
    skill.latest_version = v
    skill.save()
    return v


def test_zip_returns_302_redirect_to_storage_url(client, author):
    v = _make_published(author, name="foo", token="zip-token-xxxxxxxxxxx")
    with patch("skillshub.install.views.get_storage") as mock_get_storage:
        mock_get_storage.return_value.url.return_value = "https://cdn.example.com/skills/foo/v1.zip"
        resp = client.get(f"/install/{v.download_token}/zip")
    assert resp.status_code == 302
    assert resp["Location"] == "https://cdn.example.com/skills/foo/v1.zip"
    mock_get_storage.return_value.url.assert_called_once_with("skills/foo/v1.zip")


def test_zip_pending_version_404(client, author):
    v = _make_published(author)
    v.status = SkillVersion.STATUS_PENDING_REVIEW
    v.save()
    assert client.get(f"/install/{v.download_token}/zip").status_code == 404


def test_zip_unknown_token_404(client, db):
    assert client.get("/install/no-such-token-xxxxxxxxx/zip").status_code == 404
