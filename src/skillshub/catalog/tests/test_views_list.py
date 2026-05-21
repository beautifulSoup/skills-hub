"""Catalog 列表视图测试。

8 case: 基础展示 / 过滤未发布 / FULLTEXT (mysql跳过) / icontains (sqlite) /
tags AND / 三排序 / HTMX 分页 partial / 空状态。
"""
import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_published_skill(author, name, description="d", tags=None, install_count=0):
    """建一个 skill + 一个 published version + 设 latest_version。"""
    skill = Skill.objects.create(
        name=name,
        description=description,
        tags=tags or [],
        created_by=author,
        install_count=install_count,
    )
    v = SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path=f"skills/{name}/v1.zip",
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_PUBLISHED,
        submitted_by=author,
    )
    skill.latest_version = v
    skill.save(update_fields=["latest_version"])
    return skill


def _make_pending_skill(author, name):
    """建一个 skill + 一个 pending_review version (latest_version 留空)。"""
    skill = Skill.objects.create(name=name, description="d", created_by=author)
    SkillVersion.objects.create(
        skill=skill,
        version_no=1,
        file_path=f"skills/{name}/v1.zip",
        sha256="a" * 64,
        readme="r",
        status=SkillVersion.STATUS_PENDING_REVIEW,
        submitted_by=author,
    )
    return skill


def test_list_shows_published_skills(client, author):
    _make_published_skill(author, "demo-a")
    _make_published_skill(author, "demo-b")
    resp = client.get("/catalog/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "demo-a" in body
    assert "demo-b" in body


def test_list_hides_unpublished_skills(client, author):
    _make_published_skill(author, "shown")
    _make_pending_skill(author, "unpublished-skill")
    resp = client.get("/catalog/")
    body = resp.content.decode()
    assert "shown" in body
    assert "unpublished-skill" not in body


def test_list_search_icontains_sqlite(client, author):
    """sqlite 模式走 icontains fallback。"""
    _make_published_skill(author, "code-reviewer", description="代码审查工具")
    _make_published_skill(author, "git-helper", description="git 命令")
    resp = client.get("/catalog/", {"q": "代码"})
    body = resp.content.decode()
    assert "code-reviewer" in body
    assert "git-helper" not in body


def test_list_tags_and_filter(client, author):
    _make_published_skill(author, "ai-tool", tags=["ai", "python"])
    _make_published_skill(author, "py-only", tags=["python"])
    _make_published_skill(author, "ai-only", tags=["ai"])
    resp = client.get("/catalog/", {"tags": ["ai", "python"]})
    body = resp.content.decode()
    assert "ai-tool" in body
    assert "py-only" not in body
    assert "ai-only" not in body


def test_list_sort_by_installs_default(client, author):
    _make_published_skill(author, "low", install_count=5)
    _make_published_skill(author, "high", install_count=99)
    resp = client.get("/catalog/")
    body = resp.content.decode()
    assert body.index("high") < body.index("low")


def test_list_sort_by_newest(client, author):
    """sort=newest 按 created_at DESC。"""
    from freezegun import freeze_time

    with freeze_time("2026-01-01 00:00:00"):
        _make_published_skill(author, "first", install_count=99)
    with freeze_time("2026-01-01 00:00:01"):
        _make_published_skill(author, "second", install_count=5)
    resp = client.get("/catalog/", {"sort": "newest"})
    body = resp.content.decode()
    assert body.index("second") < body.index("first")


def test_list_htmx_pagination_partial(client, author):
    """HTMX 第二页请求返回 partial (无 base.html / DOCTYPE)。"""
    for i in range(25):
        _make_published_skill(author, f"skill-{i:02d}", install_count=100 - i)
    resp1 = client.get("/catalog/")
    assert resp1.status_code == 200
    resp2 = client.get("/catalog/", {"page": "2"}, HTTP_HX_REQUEST="true")
    assert resp2.status_code == 200
    body2 = resp2.content.decode()
    assert "<!DOCTYPE" not in body2  # partial 不含完整 page
    assert "skill-20" in body2  # 第二页前几条


def test_list_empty_state(client, db):
    """无 published skill 时空状态文案。"""
    resp = client.get("/catalog/")
    body = resp.content.decode()
    assert "暂无" in body or "没有" in body or "empty" in body.lower()


def test_list_search_q_with_special_chars_urlencoded(client, author):
    """搜索关键词含 & 字符时, 加载更多按钮 URL 必须 urlencode 而非裸 &。"""
    for i in range(25):
        _make_published_skill(author, f"item-{i:02d}", description="共同 desc")
    resp = client.get("/catalog/", {"q": "foo&inject=evil"})
    body = resp.content.decode()
    # & 必须 urlencode 为 %26
    assert "foo%26inject%3Devil" in body
    assert "foo&inject=evil" not in body  # 裸字符串绝不能出现


def test_list_invalid_sort_falls_back_to_default(client, author):
    _make_published_skill(author, "demo-a", install_count=5)
    _make_published_skill(author, "demo-b", install_count=10)
    resp = client.get("/catalog/", {"sort": "not-a-real-sort"})
    assert resp.status_code == 200
    skills = list(resp.context["skills"])
    assert skills[0].name == "demo-b"  # 默认 installs 降序


def test_list_page_out_of_range_returns_empty(client, author):
    _make_published_skill(author, "only-one")
    resp = client.get("/catalog/", {"page": "999"})
    assert resp.status_code == 200
    assert list(resp.context["skills"]) == []
    assert resp.context["has_next"] is False
