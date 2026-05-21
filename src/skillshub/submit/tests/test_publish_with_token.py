"""publish_version 自动写 download_token 测试 (T10)."""
import re
import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import Skill, SkillVersion
from skillshub.submit.services import publish_version

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_pending_version(author, name="foo"):
    skill = Skill.objects.create(name=name, description="d", created_by=author)
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path=f"skills/{name}/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PENDING_MACHINE, submitted_by=author,
    )
    return v


def test_publish_generates_22char_url_safe_token(author):
    v = _make_pending_version(author)
    assert v.download_token is None
    publish_version(v)
    v.refresh_from_db()
    assert v.download_token is not None
    assert len(v.download_token) == 22
    assert re.match(r"^[A-Za-z0-9_-]{22}$", v.download_token)


def test_publish_does_not_overwrite_existing_token(author):
    v = _make_pending_version(author)
    v.download_token = "preset-token-xxxxxxxxx"
    v.save()
    publish_version(v)
    v.refresh_from_db()
    assert v.download_token == "preset-token-xxxxxxxxx"


def test_publish_tokens_are_unique_across_versions(author):
    v1 = _make_pending_version(author, name="foo")
    v2 = _make_pending_version(author, name="bar")
    publish_version(v1)
    publish_version(v2)
    v1.refresh_from_db(); v2.refresh_from_db()
    assert v1.download_token != v2.download_token
