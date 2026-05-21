"""T6 inclusion tag 测试：version_dropdown。"""
import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template

from skillshub.submit.models import Skill, SkillVersion
from skillshub.submit.services import publish_version

User = get_user_model()


TEMPLATE_SRC = "{% load version_tags %}{% version_dropdown skill current_version %}"


def _render(skill, current_version=None):
    return Template(TEMPLATE_SRC).render(Context({"skill": skill, "current_version": current_version}))


@pytest.mark.django_db
def test_version_dropdown_renders_published_options():
    u = User.objects.create_user(username="td1", email="td1@e.com", password="x")
    s = Skill.objects.create(name="td1s", description="d", created_by=u)
    for no in [1, 2]:
        v = SkillVersion.objects.create(
            skill=s, version_no=no, file_path=f"p{no}", sha256="x" * 64,
            readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
        )
        publish_version(v)
    s.refresh_from_db()
    out = _render(s)
    assert "<option" in out
    assert 'value="1"' in out
    assert 'value="2"' in out


@pytest.mark.django_db
def test_version_dropdown_marks_latest():
    u = User.objects.create_user(username="td2", email="td2@e.com", password="x")
    s = Skill.objects.create(name="td2s", description="d", created_by=u)
    versions = []
    for no in [1, 2]:
        v = SkillVersion.objects.create(
            skill=s, version_no=no, file_path=f"p{no}", sha256="x" * 64,
            readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
        )
        publish_version(v)
        versions.append(v)
    s.refresh_from_db()
    out = _render(s, current_version=versions[0])
    # 当前选中 v1
    assert 'value="1" selected' in out
    # latest 是 v2，标记中文化
    assert "v2（最新已发布）" in out
    # v1 不带 latest 标记
    assert "v1（最新已发布）" not in out


@pytest.mark.django_db
def test_version_dropdown_default_current_is_latest():
    u = User.objects.create_user(username="td3", email="td3@e.com", password="x")
    s = Skill.objects.create(name="td3s", description="d", created_by=u)
    v = SkillVersion.objects.create(
        skill=s, version_no=1, file_path="p", sha256="x" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=u,
    )
    publish_version(v)
    s.refresh_from_db()
    out = _render(s)  # current_version=None → fallback to latest
    assert 'value="1" selected' in out


@pytest.mark.django_db
def test_version_dropdown_empty_versions():
    u = User.objects.create_user(username="td4", email="td4@e.com", password="x")
    s = Skill.objects.create(name="td4s", description="d", created_by=u)
    out = _render(s)
    assert "<option" not in out
    assert "<select" in out  # 空 select 仍渲染
