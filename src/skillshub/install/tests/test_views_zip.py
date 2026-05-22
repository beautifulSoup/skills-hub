"""install_zip_view 测试 (T10)."""
from unittest.mock import patch
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

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


@override_settings(STORAGE_BACKEND="aliyun_oss")
def test_zip_remote_backend_302_redirect(client, author):
    v = _make_published(author, name="foo", token="zip-token-xxxxxxxxxxx")
    with patch("skillshub.install.views.get_storage") as mock_get_storage:
        mock_get_storage.return_value.url.return_value = "https://cdn.example.com/skills/foo/v1.zip"
        resp = client.get(f"/install/{v.download_token}/zip")
    assert resp.status_code == 302
    assert resp["Location"] == "https://cdn.example.com/skills/foo/v1.zip"
    mock_get_storage.return_value.url.assert_called_once_with("skills/foo/v1.zip")


@override_settings(STORAGE_BACKEND="local")
def test_zip_local_backend_streams_content(client, author):
    v = _make_published(author, name="foo", token="zip-token-xxxxxxxxxxx")
    with patch("skillshub.install.views.get_storage") as mock_get_storage:
        mock_get_storage.return_value.get.return_value = b"PK\x03\x04zipbytes"
        resp = client.get(f"/install/{v.download_token}/zip")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/zip"
    assert resp.content == b"PK\x03\x04zipbytes"
    assert "attachment" in resp["Content-Disposition"]
    mock_get_storage.return_value.get.assert_called_once_with("skills/foo/v1.zip")


def test_zip_pending_version_404(client, author):
    v = _make_published(author)
    v.status = SkillVersion.STATUS_PENDING_REVIEW
    v.save()
    assert client.get(f"/install/{v.download_token}/zip").status_code == 404


def test_zip_unknown_token_404(client, db):
    assert client.get("/install/no-such-token-xxxxxxxxx/zip").status_code == 404
