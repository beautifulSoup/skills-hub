"""install_script_view 测试 (T10)."""
import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_published(author, name="demo-clean-skill", token="abc123XYZ_abcdefghijkl"):
    skill = Skill.objects.create(name=name, description="d", created_by=author)
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path=f"skills/{name}/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=author, download_token=token,
    )
    skill.latest_version = v
    skill.save(update_fields=["latest_version"])
    return v


def test_sh_default_returns_200_shell_content(client, author):
    v = _make_published(author)
    resp = client.get(f"/install/{v.download_token}.sh")
    assert resp.status_code == 200
    assert "shell" in resp["Content-Type"].lower()
    body = resp.content.decode()
    assert 'SKILL_NAME="demo-clean-skill"' in body
    assert "$HOME/.claude/skills/demo-clean-skill/" in body
    assert "set -euo pipefail" in body
    assert "rm -rf" in body
    assert "curl -fsSL" in body
    assert "unzip" in body
    assert "SKILL.md" in body


def test_sh_with_workbuddy_tool(client, author):
    v = _make_published(author)
    resp = client.get(f"/install/{v.download_token}.sh?tool=workbuddy")
    body = resp.content.decode()
    assert "$HOME/.workbuddy/skills/demo-clean-skill/" in body


def test_sh_with_os_macos_same_path_as_linux(client, author):
    v = _make_published(author)
    resp = client.get(f"/install/{v.download_token}.sh?os=macos")
    body = resp.content.decode()
    assert "$HOME/.claude/skills/demo-clean-skill/" in body


def test_sh_invalid_tool_404(client, author):
    v = _make_published(author)
    assert client.get(f"/install/{v.download_token}.sh?tool=does-not-exist").status_code == 404


def test_sh_invalid_os_404(client, author):
    v = _make_published(author)
    assert client.get(f"/install/{v.download_token}.sh?os=freebsd").status_code == 404


def test_sh_does_not_allow_os_windows(client, author):
    v = _make_published(author)
    assert client.get(f"/install/{v.download_token}.sh?os=windows").status_code == 404


def test_sh_pending_version_404(client, author):
    v = _make_published(author)
    v.status = SkillVersion.STATUS_PENDING_REVIEW
    v.save()
    assert client.get(f"/install/{v.download_token}.sh").status_code == 404


def test_sh_unknown_token_404(client, db):
    assert client.get("/install/this-token-does-not-exist-12345.sh").status_code == 404


def test_ps1_default_returns_200_powershell_content(client, author):
    v = _make_published(author)
    resp = client.get(f"/install/{v.download_token}.ps1")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "$ErrorActionPreference = 'Stop'" in body
    assert "$env:USERPROFILE\\.claude\\skills\\demo-clean-skill\\" in body
    assert "Invoke-WebRequest" in body
    assert "Expand-Archive" in body
    assert "Move-Item" in body


def test_ps1_with_workbuddy(client, author):
    v = _make_published(author)
    resp = client.get(f"/install/{v.download_token}.ps1?tool=workbuddy")
    body = resp.content.decode()
    assert "$env:USERPROFILE\\.workbuddy\\skills\\demo-clean-skill\\" in body


def test_ps1_does_not_allow_os_linux(client, author):
    v = _make_published(author)
    assert client.get(f"/install/{v.download_token}.ps1?os=linux").status_code == 404


def test_ps1_does_not_allow_os_macos(client, author):
    v = _make_published(author)
    assert client.get(f"/install/{v.download_token}.ps1?os=macos").status_code == 404
