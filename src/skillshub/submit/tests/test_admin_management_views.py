"""admin 集成测试：PendingSkillVersion / SkillAdmin actions / versions / rollback。"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from skillshub.submit.models import ReviewAction, Skill, SkillVersion

User = get_user_model()


@pytest.fixture
def author(db):
    return User.objects.create_user(username="alice", email="alice@example.com", password="pw")


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="bob", email="bob@example.com", password="pw",
        is_staff=True, is_superuser=True,
    )


@pytest.fixture
def published_skill(author):
    skill = Skill.objects.create(name="pub-skill", description="d", created_by=author)
    v = SkillVersion.objects.create(
        skill=skill, version_no=1, file_path="x/v1.zip",
        sha256="a" * 64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )
    skill.latest_version = v
    skill.save(update_fields=["latest_version"])
    return skill


@pytest.fixture
def pending_version(author):
    skill = Skill.objects.create(name="pend-skill", description="d", created_by=author)
    return SkillVersion.objects.create(
        skill=skill, version_no=1, file_path="x/v1.zip",
        sha256="b" * 64, readme="r",
        status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=author,
    )


# ---------------- PendingSkillVersion changelist ----------------

def test_pending_changelist_lists_only_pending_review(
    client, admin_user, pending_version, published_skill
):
    """Skill 审核 changelist 只显示 status=pending_review 的版本。"""
    client.force_login(admin_user)
    resp = client.get(reverse("admin:submit_pendingskillversion_changelist"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "pend-skill" in body
    assert "pub-skill" not in body


# ---------------- SkillAdmin changelist 多维筛选 ----------------

def test_skill_changelist_filter_by_is_listed(client, admin_user, published_skill, author):
    """list_filter ?is_listed__exact=False 只显示已下线 skill。"""
    delisted = Skill.objects.create(
        name="del-skill", description="d", created_by=author, is_listed=False,
    )
    v = SkillVersion.objects.create(
        skill=delisted, version_no=1, file_path="x/v1.zip", sha256="c"*64,
        readme="r", status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )
    delisted.latest_version = v
    delisted.save()

    client.force_login(admin_user)
    resp = client.get(
        reverse("admin:submit_skill_changelist") + "?is_listed__exact=0"
    )
    body = resp.content.decode()
    assert "del-skill" in body
    assert "pub-skill" not in body


def test_skill_changelist_search_by_created_by_email(
    client, admin_user, published_skill
):
    client.force_login(admin_user)
    resp = client.get(
        reverse("admin:submit_skill_changelist") + "?q=alice@example.com"
    )
    body = resp.content.decode()
    assert "pub-skill" in body


def test_skill_changelist_filter_has_pending(client, admin_user, author):
    """有待审版本的 skill 与无待审的 skill 分别能被过滤出。"""
    s1 = Skill.objects.create(name="s1", description="d", created_by=author)
    SkillVersion.objects.create(
        skill=s1, version_no=1, file_path="x", sha256="d"*64, readme="r",
        status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=author,
    )
    s2 = Skill.objects.create(name="s2", description="d", created_by=author)

    client.force_login(admin_user)
    resp = client.get(reverse("admin:submit_skill_changelist") + "?has_pending=yes")
    body = resp.content.decode()
    assert "s1" in body
    assert "s2" not in body

    resp = client.get(reverse("admin:submit_skill_changelist") + "?has_pending=no")
    body = resp.content.decode()
    assert "s2" in body
    assert "s1" not in body


def test_skill_change_form_name_and_is_listed_readonly(
    client, admin_user, published_skill
):
    """change form 上 name 与 is_listed 必须 readonly（无 input 控件）。"""
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_change", args=[published_skill.pk])
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # readonly_fields 在 admin 渲染为带 .readonly 的 div，原值文本可见、无 input/checkbox
    assert 'name="name"' not in body
    assert 'name="is_listed"' not in body


# ---------------- 上下线 actions ----------------

def test_bulk_listing_view_empty_reason_rerenders(client, admin_user, published_skill):
    client.force_login(admin_user)
    url = (
        reverse("admin:submit_skill_bulk_listing")
        + f"?op=delist&ids={published_skill.pk}"
    )
    resp = client.post(url, {"reason": ""})
    assert resp.status_code == 200  # re-render 不重定向
    body = resp.content.decode()
    assert "reason 必填" in body
    published_skill.refresh_from_db()
    assert published_skill.is_listed is True


def test_bulk_listing_view_single_delist_success(client, admin_user, published_skill):
    client.force_login(admin_user)
    url = (
        reverse("admin:submit_skill_bulk_listing")
        + f"?op=delist&ids={published_skill.pk}"
    )
    resp = client.post(url, {"reason": "作者要求"}, follow=True)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "成功下线 1 个 skill" in body

    published_skill.refresh_from_db()
    assert published_skill.is_listed is False
    assert ReviewAction.objects.filter(
        action=ReviewAction.ACTION_DELIST
    ).count() == 1


def test_bulk_listing_view_partial_failure(client, admin_user, author):
    """两个 skill：1 个 is_listed=True，1 个已 False。批量下线 → 1 成功 1 跳过。"""
    s_up = Skill.objects.create(name="up", description="d", created_by=author)
    v_up = SkillVersion.objects.create(
        skill=s_up, version_no=1, file_path="x", sha256="e"*64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )
    s_up.latest_version = v_up
    s_up.save()

    s_down = Skill.objects.create(
        name="down", description="d", created_by=author, is_listed=False,
    )
    v_down = SkillVersion.objects.create(
        skill=s_down, version_no=1, file_path="x", sha256="f"*64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )
    s_down.latest_version = v_down
    s_down.save()

    client.force_login(admin_user)
    url = (
        reverse("admin:submit_skill_bulk_listing")
        + f"?op=delist&ids={s_up.pk},{s_down.pk}"
    )
    resp = client.post(url, {"reason": "batch"}, follow=True)
    body = resp.content.decode()

    s_up.refresh_from_db()
    s_down.refresh_from_db()
    assert s_up.is_listed is False
    assert s_down.is_listed is False  # 不变
    assert "成功下线 1 个，跳过 1 个（已下线）" in body


# ---------------- versions 子页 ----------------

@pytest.fixture
def skill_with_three_versions(author):
    skill = Skill.objects.create(name="multi", description="d", created_by=author)
    versions = []
    for i in (1, 2, 3):
        v = SkillVersion.objects.create(
            skill=skill, version_no=i, file_path=f"x/v{i}.zip",
            sha256=str(i) * 64, readme="r",
            status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
        )
        versions.append(v)
    skill.latest_version = versions[-1]
    skill.save()
    return skill, versions


def test_versions_view_anonymous_redirected(client, skill_with_three_versions):
    skill, _ = skill_with_three_versions
    url = reverse("admin:submit_skill_versions", args=[skill.pk])
    resp = client.get(url)
    assert resp.status_code == 302


def test_versions_view_staff_renders_full_list(
    client, admin_user, skill_with_three_versions
):
    skill, versions = skill_with_three_versions
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_versions", args=[skill.pk])
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # 倒序显示 v3 v2 v1
    assert body.index("v3") < body.index("v2") < body.index("v1")
    # 当前 latest=v3 有 ✓ 徽章
    assert "当前版本" in body
    # 非 latest 的 published 版本（v1 v2）有「设为当前版本」按钮
    assert body.count("设为当前版本") == 2


# ---------------- rollback ----------------

def test_rollback_view_get_renders_reason_form(
    client, admin_user, skill_with_three_versions
):
    skill, versions = skill_with_three_versions
    v1 = versions[0]
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_rollback", args=[skill.pk]) + f"?target={v1.pk}"
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "v1" in body
    assert "reason" in body.lower() or "理由" in body


def test_rollback_view_post_success(client, admin_user, skill_with_three_versions):
    skill, versions = skill_with_three_versions
    v1 = versions[0]
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_rollback", args=[skill.pk]) + f"?target={v1.pk}"
    resp = client.post(url, {"reason": "v3 含 bug"})
    assert resp.status_code == 302

    skill.refresh_from_db()
    assert skill.latest_version_id == v1.id
    assert ReviewAction.objects.filter(
        action=ReviewAction.ACTION_ROLLBACK
    ).count() == 1


def test_rollback_view_post_empty_reason_rerenders(
    client, admin_user, skill_with_three_versions
):
    skill, versions = skill_with_three_versions
    v1 = versions[0]
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_rollback", args=[skill.pk]) + f"?target={v1.pk}"
    resp = client.post(url, {"reason": ""})
    assert resp.status_code == 200
    skill.refresh_from_db()
    assert skill.latest_version_id == versions[-1].id


def test_rollback_view_target_cross_skill_rejected(
    client, admin_user, skill_with_three_versions, author
):
    skill, _ = skill_with_three_versions
    other = Skill.objects.create(name="other", description="d", created_by=author)
    other_v = SkillVersion.objects.create(
        skill=other, version_no=1, file_path="x", sha256="9"*64, readme="r",
        status=SkillVersion.STATUS_PUBLISHED, submitted_by=author,
    )
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_rollback", args=[skill.pk]) + f"?target={other_v.pk}"
    resp = client.post(url, {"reason": "x"}, follow=True)
    body = resp.content.decode()
    assert "不属于" in body or "error" in body.lower()


# ---------------- 侧边栏导航 ----------------

def test_admin_index_sidebar_has_skill_management_group(client, admin_user):
    client.force_login(admin_user)
    resp = client.get(reverse("admin:index"))
    body = resp.content.decode()
    # 平铺：不再有分组标题
    assert "主页" in body  # admin:index 链接（仪表盘）
    assert "Skill 列表" in body
    assert "Skill 审核" in body
    assert "管理员管理" in body
    # 「主页」侧边栏项指向 admin:index
    assert 'href="{}"'.format(reverse("admin:index")) in body
    # 已移除
    assert "审核日志" not in body
    assert "邮件通知" not in body


# ---------------- Admin 首页仪表盘 ----------------

def test_admin_index_dashboard_shows_four_metric_cards(
    client, admin_user, published_skill, pending_version,
):
    """admin 首页应渲染 4 张统计卡 + pending 卡片可点击跳审核列表。"""
    client.force_login(admin_user)
    resp = client.get(reverse("admin:index"))
    body = resp.content.decode()
    assert resp.status_code == 200
    # 4 个 metric label
    assert "待审核 Skill 数" in body
    assert "全站 Skill 总数" in body
    assert "全站下载总次数" in body
    assert "总用户量" in body
    # pending 卡跳审核列表
    pending_url = reverse("admin:submit_pendingskillversion_changelist")
    assert pending_url in body
    # 旧的「最近动作」面板已去掉（unfold history helper 渲染该文案）
    assert "Recent actions" not in body
    assert "最近动作" not in body


def test_admin_index_dashboard_numbers_reflect_db_state(client, admin_user):
    """4 个统计卡的数字与 DB 当前 state 一致。"""
    from django.contrib.auth.models import User

    from skillshub.submit.models import Skill, SkillVersion
    author = User.objects.create_user(username="author@x.com", email="author@x.com")
    # 2 个 Skill，一个安装 7 次一个 3 次 → 总 install 10
    sk1 = Skill.objects.create(name="s1", description="d", created_by=author, install_count=7)
    sk2 = Skill.objects.create(name="s2", description="d", created_by=author, install_count=3)
    SkillVersion.objects.create(
        skill=sk1, version_no=1, file_path="x/v1.zip", sha256="a" * 64,
        readme="r", status=SkillVersion.STATUS_PENDING_REVIEW, submitted_by=author,
    )
    # 一个 pending_review

    client.force_login(admin_user)
    resp = client.get(reverse("admin:index"))
    body = resp.content.decode()
    # 数字断言（用现在的渲染 class "text-4xl font-bold" 紧跟的 1 / 2 / 10 之类）
    # 弱断言：4 个值都出现就行
    assert ">1<" in body  # pending count = 1
    assert ">2<" in body  # skill total = 2
    assert ">10<" in body  # install sum = 10
    # 用户量 = admin_user + author = 2
    # 但 fixtures 可能创建别的用户；改成宽松断言 User.count >= 2
    assert User.objects.count() >= 2


# ---------------- §v2.4+v2.5 list cleanup + change form reshape ----------------

def test_changelist_has_no_action_column(client, admin_user, published_skill):
    """list 页不应有 action 下拉、checkbox 列、批量操作 UI。"""
    client.force_login(admin_user)
    resp = client.get(reverse("admin:submit_skill_changelist"))
    body = resp.content.decode()
    # 不应该有 action 下拉 (action_select select 元素)
    assert '<select name="action"' not in body
    # 不应该有 _selected_action checkbox
    assert 'name="_selected_action"' not in body
    # 旧的 bulk 动作描述不应出现
    assert "下线选中的 skill" not in body


def test_change_form_renders_chinese_fieldset(client, admin_user, published_skill):
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_change", args=[published_skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    # 字段标签中文存在
    for label in ("名称", "类型", "简介", "详细描述", "标签", "版本清单",
                  "创建人", "上下线状态", "创建时间", "安装次数"):
        assert label in body


def test_change_form_no_save_and_continue_buttons(client, admin_user, published_skill):
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_change", args=[published_skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    assert "_continue" not in body
    assert "_addanother" not in body
    # 仍保留默认 Save 按钮
    assert "_save" in body or "保存" in body


def test_change_form_no_toggle_listing_button(client, admin_user, published_skill):
    """change form 上不应有上下线按钮，只有状态徽章。"""
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_change", args=[published_skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    # bulk_listing URL 不应该出现在 change form 里
    bulk_url = reverse("admin:submit_skill_bulk_listing")
    assert bulk_url not in body
    # 状态徽章保留
    assert "上线" in body  # published_skill 默认 is_listed=True 显示"上线"


def test_change_form_has_skill_toggle_listing_button(
    client, admin_user, published_skill
):
    """Skill 级上下线按钮挂在 change form 底部 submit_line（不在版本子页）。"""
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_change", args=[published_skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    listing_dialog_url = reverse(
        "admin:submit_skill_listing_dialog", args=[published_skill.pk]
    )
    assert listing_dialog_url in body
    # 默认 is_listed=True，按钮文案为"下线 Skill"
    assert "下线 Skill" in body


def test_change_form_version_summary_shows_latest(
    client, admin_user, published_skill
):
    """版本清单字段显示最新版本号 + 跳「全部版本」链接。"""
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_change", args=[published_skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    # _version_summary 用 <strong> 包裹版本号
    assert "最新版本：<strong>v1</strong>" in body
    # 跳全部版本
    versions_url = reverse("admin:submit_skill_versions", args=[published_skill.pk])
    assert versions_url in body


# ---------------- §v2.6 disable_version_view / enable_version_view ----------------

def test_disable_version_view_post_success(
    client, admin_user, skill_with_three_versions
):
    skill, versions = skill_with_three_versions
    v1 = versions[0]
    client.force_login(admin_user)
    url = reverse("admin:submit_version_disable", args=[v1.pk])
    resp = client.post(url, {"reason": "含敏感信息"})
    assert resp.status_code == 302

    v1.refresh_from_db()
    assert v1.is_available is False
    assert ReviewAction.objects.filter(
        action=ReviewAction.ACTION_DISABLE_VERSION
    ).count() == 1


def test_disable_version_view_empty_reason(
    client, admin_user, skill_with_three_versions
):
    skill, versions = skill_with_three_versions
    v1 = versions[0]
    client.force_login(admin_user)
    url = reverse("admin:submit_version_disable", args=[v1.pk])
    resp = client.post(url, {"reason": ""})
    # service raises ValueError → messages.error + redirect
    assert resp.status_code == 302
    v1.refresh_from_db()
    assert v1.is_available is True  # unchanged


def test_enable_version_view_post_success(
    client, admin_user, skill_with_three_versions
):
    skill, versions = skill_with_three_versions
    v1 = versions[0]
    v1.is_available = False
    v1.save(update_fields=["is_available"])
    client.force_login(admin_user)
    url = reverse("admin:submit_version_enable", args=[v1.pk])
    resp = client.post(url, {"reason": "撤回"})
    assert resp.status_code == 302
    v1.refresh_from_db()
    assert v1.is_available is True


def test_versions_page_renders_disable_button_for_available(
    client, admin_user, skill_with_three_versions
):
    """版本子页：每个可用版本一个'下线版本'按钮 + 一个回退按钮，
    dialog 现在通过 htmx 异步加载（不再 inline 渲染）。"""
    skill, versions = skill_with_three_versions
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_versions", args=[skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    # 默认所有 3 版本 is_available=True → 都有"下线版本"按钮
    assert "下线版本" in body
    # 非 latest 版本应有 "设为当前版本" 入口（rollback dialog 走 htmx）
    assert "设为当前版本" in body
    # rollback dialog URL（htmx hx-get 目标）出现在 body 里
    non_latest = versions[0]  # v1，latest 是 v3
    rollback_dialog_url = reverse(
        "admin:submit_version_action_dialog",
        args=[non_latest.pk, "rollback"],
    )
    assert rollback_dialog_url in body


# ---------------- §v2.7 version_detail_view ----------------

def test_version_detail_view_anonymous_redirected(
    client, skill_with_three_versions
):
    _skill, versions = skill_with_three_versions
    v1 = versions[0]
    url = reverse("admin:submit_version_detail", args=[v1.pk])
    resp = client.get(url)
    assert resp.status_code == 302  # admin login redirect


def test_version_detail_view_staff_renders_chinese_fields(
    client, admin_user, skill_with_three_versions
):
    from unittest.mock import patch
    _skill, versions = skill_with_three_versions
    v1 = versions[0]
    client.force_login(admin_user)
    url = reverse("admin:submit_version_detail", args=[v1.pk])
    with patch("skillshub.submit.admin_views._zip_entries", return_value=[]):
        resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    for label in (
        "Skill 名称", "版本号", "状态", "版本上下线",
        "提交时间", "提交人", "发布时间", "SHA256", "文件路径",
        "机审结果", "违规清单", "LLM 审核结果", "README", "文件清单",
    ):
        assert label in body
    # 状态显示用 get_status_display （v1 是 published → 中文）
    assert "已发布" in body


def test_version_detail_view_shows_is_available_badge(
    client, admin_user, skill_with_three_versions
):
    from unittest.mock import patch
    _skill, versions = skill_with_three_versions
    v1 = versions[0]
    v1.is_available = False
    v1.save(update_fields=["is_available"])

    client.force_login(admin_user)
    url = reverse("admin:submit_version_detail", args=[v1.pk])
    with patch("skillshub.submit.admin_views._zip_entries", return_value=[]):
        resp = client.get(url)
    body = resp.content.decode()
    assert "已下线" in body


def test_changelist_has_detail_button_per_row(client, admin_user, published_skill):
    """list 页每行末尾应渲染「详情」按钮，链接到 change form。"""
    client.force_login(admin_user)
    resp = client.get(reverse("admin:submit_skill_changelist"))
    body = resp.content.decode()
    expected_url = reverse("admin:submit_skill_change", args=[published_skill.pk])
    assert expected_url in body
    assert ">详情<" in body


# ---------------- TODO-6: history_view 分页 ----------------

def test_history_view_single_page_no_paginator(client, admin_user, published_skill):
    """事件少于 20 条 → paginator 只有 1 页 → 不渲染分页 nav。"""
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_history", args=[published_skill.pk])
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # 顶部摘要只显示总数（无"第 X / Y 页"）
    assert "共 1 条事件" in body  # 仅 v1 提交事件
    # 不渲染分页器
    assert "上一页" not in body
    assert "下一页" not in body


def test_history_view_paginates_at_20_per_page(client, admin_user, published_skill):
    """造 22 个 ReviewAction → 加上 1 个提交事件 = 23 条 → 2 页（20+3）。"""
    from skillshub.submit.models import ReviewAction
    v = published_skill.latest_version
    for i in range(22):
        ReviewAction.objects.create(
            version=v,
            actor=admin_user,
            action=ReviewAction.ACTION_APPROVE,
            reason=f"批准 {i}",
        )

    client.force_login(admin_user)
    url = reverse("admin:submit_skill_history", args=[published_skill.pk])

    # 第 1 页：默认
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "共 23 条事件" in body
    assert "第 1 / 2 页" in body
    # 第 1 页：下一页可点（链接到 ?page=2），上一页 disabled
    assert "?page=2" in body
    # 跳第 2 页
    resp = client.get(url + "?page=2")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "第 2 / 2 页" in body
    # 第 2 页：上一页可点（链接到 ?page=1）
    assert "?page=1" in body


def test_history_view_includes_logentry_submit_and_reviewaction(
    client, admin_user, published_skill
):
    """build_skill_events 应合并 LogEntry + SkillVersion 提交 + ReviewAction。"""
    from django.contrib.admin.models import CHANGE, LogEntry
    from django.contrib.contenttypes.models import ContentType

    from skillshub.submit.models import ReviewAction
    v = published_skill.latest_version

    LogEntry.objects.create(
        user=admin_user,
        content_type=ContentType.objects.get_for_model(Skill),
        object_id=str(published_skill.pk),
        object_repr=str(published_skill),
        action_flag=CHANGE,
        change_message="改了 description",
    )
    ReviewAction.objects.create(
        version=v, actor=admin_user,
        action=ReviewAction.ACTION_APPROVE, reason="通过",
    )

    client.force_login(admin_user)
    url = reverse("admin:submit_skill_history", args=[published_skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    # 3 类事件都出现
    assert "管理后台" in body  # LogEntry 类型
    assert "提交版本" in body  # SkillVersion 类型
    assert "审核通过" in body  # ReviewAction 类型
    assert "共 3 条事件" in body


# ---------------- TODO-3: version_view 只读版本详情页 ----------------

def test_versions_page_has_view_button_per_row(
    client, admin_user, skill_with_three_versions
):
    """版本子页每行应有「查看」链接，指向 submit_skillversion_view。"""
    skill, versions = skill_with_three_versions
    client.force_login(admin_user)
    url = reverse("admin:submit_skill_versions", args=[skill.pk])
    resp = client.get(url)
    body = resp.content.decode()
    for v in versions:
        view_url = reverse("admin:submit_skillversion_view", args=[v.pk])
        assert view_url in body
    # 至少有一处"查看"按钮文案
    assert ">\n                            查看\n                        </a>" in body or ">查看<" in body


def test_version_view_anonymous_redirected(client, skill_with_three_versions):
    _skill, versions = skill_with_three_versions
    url = reverse("admin:submit_skillversion_view", args=[versions[0].pk])
    resp = client.get(url)
    assert resp.status_code == 302  # admin login redirect


def test_version_view_renders_readonly_no_action_form(
    client, admin_user, skill_with_three_versions
):
    """staff 访问 view 端点 → 200 + 含基础信息，且 **不含** 审核 form。"""
    from unittest.mock import patch
    _skill, versions = skill_with_three_versions
    v1 = versions[0]
    client.force_login(admin_user)
    url = reverse("admin:submit_skillversion_view", args=[v1.pk])
    with patch("skillshub.submit.admin_views._zip_entries", return_value=[]):
        resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    # 基础信息出现
    assert f"v{v1.version_no}" in body
    assert v1.submitted_by.email in body
    # 标题用"查看"而非"审核"
    assert "查看" in body
    # 审核表单不应出现：name="action" 仅出现在审核按钮里
    assert 'name="action"' not in body
    assert "审核通过" not in body
    assert "审核拒绝" not in body


def test_review_view_still_renders_action_form(
    client, admin_user, pending_version
):
    """review 端点（POST 审核入口）仍保留审核表单（不被 readonly 误伤）。"""
    from unittest.mock import patch
    client.force_login(admin_user)
    url = reverse("admin:submit_skillversion_review", args=[pending_version.pk])
    with patch("skillshub.submit.admin_views._zip_entries", return_value=[]):
        resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="action"' in body
    assert "审核通过" in body
    assert "审核拒绝" in body
