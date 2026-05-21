"""Catalog 详情视图测试 (6 case)。"""
import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.models import Skill, SkillVersion

User = get_user_model()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


def _make_skill_with_versions(author, name, version_specs):
    """version_specs: list of (version_no, status, readme).

    返回 (skill, dict[version_no, SkillVersion])。设 latest_version 为最大已发布版本。
    """
    skill = Skill.objects.create(name=name, description="d", created_by=author)
    versions = {}
    latest_published = None
    for vno, status, readme in version_specs:
        v = SkillVersion.objects.create(
            skill=skill,
            version_no=vno,
            file_path=f"skills/{name}/v{vno}.zip",
            sha256="a" * 64,
            readme=readme,
            status=status,
            submitted_by=author,
        )
        versions[vno] = v
        if status == SkillVersion.STATUS_PUBLISHED:
            if latest_published is None or vno > latest_published.version_no:
                latest_published = v
    if latest_published:
        skill.latest_version = latest_published
        skill.save(update_fields=["latest_version"])
    return skill, versions


def test_detail_default_latest(client, author):
    skill, vs = _make_skill_with_versions(
        author, "demo", [
            (1, SkillVersion.STATUS_PUBLISHED, "# v1 readme"),
            (2, SkillVersion.STATUS_PUBLISHED, "# v2 readme latest"),
        ],
    )
    resp = client.get("/catalog/demo/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "v2 readme latest" in body  # 默认渲染 latest = v2


def test_detail_specific_version(client, author):
    skill, vs = _make_skill_with_versions(
        author, "demo", [
            (1, SkillVersion.STATUS_PUBLISHED, "# v1 readme"),
            (2, SkillVersion.STATUS_PUBLISHED, "# v2 readme latest"),
        ],
    )
    resp = client.get("/catalog/demo/?v=1")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "v1 readme" in body
    assert "v2 readme latest" not in body


@pytest.mark.django_db
def test_detail_404_nonexistent_skill(client):
    resp = client.get("/catalog/never-existed/")
    assert resp.status_code == 404


def test_detail_404_unpublished_skill(client, author):
    """skill 仅有 pending_review 版本 (latest_version 是 None) → 404。"""
    skill, _ = _make_skill_with_versions(
        author, "draft", [(1, SkillVersion.STATUS_PENDING_REVIEW, "r")],
    )
    resp = client.get("/catalog/draft/")
    assert resp.status_code == 404


def test_detail_v_param_must_be_published(client, author):
    """?v=N 指向非 published 版本 → 404 (防泄露未发布内容)。"""
    skill, _ = _make_skill_with_versions(
        author, "demo", [
            (1, SkillVersion.STATUS_PUBLISHED, "ok"),
            (2, SkillVersion.STATUS_PENDING_REVIEW, "secret-draft"),
        ],
    )
    resp = client.get("/catalog/demo/?v=2")
    assert resp.status_code == 404


def test_detail_404_when_v_param_non_numeric(client, author):
    """?v=abc (非数字) → 404，不应 500。"""
    _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    resp = client.get("/catalog/demo/?v=abc")
    assert resp.status_code == 404


def test_detail_renders_markdown(client, author):
    skill, _ = _make_skill_with_versions(
        author, "demo", [
            (1, SkillVersion.STATUS_PUBLISHED, "# Heading\n\n- list item\n\n<script>alert(1)</script>"),
        ],
    )
    resp = client.get("/catalog/demo/")
    body = resp.content.decode()
    assert "<h1>Heading</h1>" in body
    assert "<li>list item</li>" in body
    # XSS 防御：readme 里的 <script>alert(1)</script> 应被 bleach 剥除
    # （注：页面本身合法持有 <script src=...>（alpinejs/htmx）以及 install-block 内联脚本，
    # 所以不能用裸 `"<script>" not in body` 判断。这里验证 readme XSS payload 没有原样落到 HTML。）
    assert "<script>alert(1)</script>" not in body
    # alert(1) 可能作为 plain text 留下 (bleach strip=True 行为) — 不强制 assert not in


def test_detail_contains_install_block(client, author):
    skill, _ = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    # macOS UA → 预选 macos
    resp = client.get("/catalog/demo/", HTTP_USER_AGENT="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
    body = resp.content.decode()
    assert 'class="install-block' in body
    assert 'installBlock(' in body
    assert 'os: "macos"' in body
    assert "claude-code" in body and "workbuddy" in body


def test_detail_install_block_renders_token(client, author):
    import secrets
    skill, vs = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    version = vs[1]
    if version.download_token is None:
        version.download_token = secrets.token_urlsafe(16)
        version.save()
    resp = client.get("/catalog/demo/")
    body = resp.content.decode()
    assert version.download_token in body


# ---------------- 公开 detail：owner 与普通用户一致，无时间线 ----------------

def test_public_detail_no_timeline_for_owner(client, author):
    """公开 detail 路由：owner 访问也不显示时间线（owner 体验改走 /catalog/mine/<name>/）。"""
    from skillshub.submit.models import ReviewAction
    skill, vs = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    ReviewAction.objects.create(
        version=vs[1], actor=author,
        action=ReviewAction.ACTION_APPROVE, reason="审核通过备注",
    )
    client.force_login(author)
    resp = client.get("/catalog/demo/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "提交与审核历史" not in body
    assert "审核通过备注" not in body


def test_public_detail_no_timeline_for_non_owner(client, author, django_user_model):
    from skillshub.submit.models import ReviewAction
    skill, vs = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    ReviewAction.objects.create(
        version=vs[1], actor=author,
        action=ReviewAction.ACTION_APPROVE, reason="审核通过备注",
    )
    other = django_user_model.objects.create_user(
        username="bob", email="bob@example.com", password="pw",
    )
    client.force_login(other)
    resp = client.get("/catalog/demo/")
    body = resp.content.decode()
    assert "提交与审核历史" not in body
    assert "审核通过备注" not in body


def test_public_detail_no_timeline_for_anonymous(client, author):
    skill, vs = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    resp = client.get("/catalog/demo/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "提交与审核历史" not in body


# ---------------- /catalog/mine/<name>/ — owner-only detail ----------------

def test_mine_detail_owner_sees_timeline_and_resubmit(client, author):
    """owner 访问 mine_detail → 时间线 + 「重新提交」入口都渲染。"""
    from skillshub.submit.models import ReviewAction
    skill, vs = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    ReviewAction.objects.create(
        version=vs[1], actor=author,
        action=ReviewAction.ACTION_APPROVE, reason="审核通过备注",
    )
    client.force_login(author)
    resp = client.get("/catalog/mine/demo/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "提交与审核历史" in body
    assert "审核通过备注" in body
    # 重新提交按钮跳 /submit/?skill=demo
    assert "/submit/?skill=demo" in body
    assert "重新提交此 Skill" in body


def test_mine_detail_non_owner_404(client, author, django_user_model):
    skill, vs = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    other = django_user_model.objects.create_user(
        username="bob", email="bob@example.com", password="pw",
    )
    client.force_login(other)
    resp = client.get("/catalog/mine/demo/")
    assert resp.status_code == 404


def test_mine_detail_anonymous_redirects_to_login(client, author):
    skill, vs = _make_skill_with_versions(
        author, "demo", [(1, SkillVersion.STATUS_PUBLISHED, "ok")],
    )
    resp = client.get("/catalog/mine/demo/")
    # @login_required → 302 重定向到 login
    assert resp.status_code == 302


def test_mine_detail_shows_pending_versions_in_dropdown(client, author):
    """owner 可以在 mine_detail 看到非 published 版本（pending / rejected 等）。"""
    skill, vs = _make_skill_with_versions(
        author, "demo", [
            (1, SkillVersion.STATUS_PUBLISHED, "v1 readme"),
            (2, SkillVersion.STATUS_REJECTED, "v2 was rejected"),
            (3, SkillVersion.STATUS_PENDING_REVIEW, "v3 pending"),
        ],
    )
    client.force_login(author)
    resp = client.get("/catalog/mine/demo/")
    body = resp.content.decode()
    assert resp.status_code == 200
    # 默认显示最新一版（v3, pending_review）
    assert "v3" in body and "pending_review" not in body  # 用户看 get_status_display 中文
    # 下拉里 3 个版本都出现
    assert "v1" in body and "v2" in body and "v3" in body
    # 拒绝 / 待审等状态文案都出现
    assert "已发布" in body or "已拒绝" in body or "待审核" in body


def test_mine_detail_v_param_switches_version(client, author):
    """?v=1 切到 v1（即便不是 latest）。"""
    skill, vs = _make_skill_with_versions(
        author, "demo", [
            (1, SkillVersion.STATUS_PUBLISHED, "v1 readme content"),
            (2, SkillVersion.STATUS_PUBLISHED, "v2 readme content"),
        ],
    )
    client.force_login(author)
    resp = client.get("/catalog/mine/demo/?v=1")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "v1 readme content" in body
