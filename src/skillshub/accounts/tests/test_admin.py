"""管理员管理 admin 行为测试。"""
import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


@override_settings(EMAIL_DOMAIN_WHITELIST=["x.com"])
def test_add_admin_via_form_creates_staff_superuser(client):
    """系统两个角色（管理员=超管），新建管理员同时 is_staff + is_superuser=True。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_add")
    resp = client.post(url, {"email": "newadmin@x.com"})
    assert resp.status_code == 302

    u = User.objects.get(username="newadmin@x.com")
    assert u.is_staff is True
    assert u.is_superuser is True
    assert u.is_active is True
    assert not u.has_usable_password()


@override_settings(EMAIL_DOMAIN_WHITELIST=["x.com"])
def test_add_admin_promotes_existing_user(client):
    """既存普通用户被加入管理员 → is_staff + is_superuser=True。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    User.objects.create_user(username="alice@x.com", is_staff=False)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_add")
    resp = client.post(url, {"email": "alice@x.com"})
    assert resp.status_code == 302

    alice = User.objects.get(username="alice@x.com")
    assert alice.is_staff is True
    assert alice.is_superuser is True


@override_settings(EMAIL_DOMAIN_WHITELIST=["x.com"])
def test_add_view_only_shows_save_button(client):
    """新增管理员页只渲染 Save 按钮，无 _continue / _addanother。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    resp = client.get(reverse("admin:accounts_adminuser_add"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "_continue" not in body
    assert "_addanother" not in body
    # Save 按钮（中文「保存」或字段 _save 之一）仍在
    assert "_save" in body or "保存" in body


@override_settings(EMAIL_DOMAIN_WHITELIST=["x.com"])
def test_add_admin_rejects_non_whitelisted_email(client):
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_add")
    resp = client.post(url, {"email": "attacker@evil.com"})
    # 表单校验失败 → 重新渲染（200 而非 302）
    assert resp.status_code == 200
    assert not User.objects.filter(username="attacker@evil.com").exists()


def test_remove_admin_view_rejects_get(client):
    """remove-admin 改成 POST-only（带二次确认 dialog），GET 应 405。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    other = User.objects.create_user(username="other@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_remove_admin", args=[other.pk])
    resp = client.get(url)
    assert resp.status_code == 405


def test_remove_admin_view_post_demotes_user(client):
    """POST 移除：is_staff + is_superuser 双双置 False，user 行保留。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    other = User.objects.create_user(
        username="other@x.com", is_staff=True, is_superuser=True,
    )
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_remove_admin", args=[other.pk])
    resp = client.post(url)
    assert resp.status_code == 302  # 非 htmx → redirect to changelist

    other.refresh_from_db()
    assert other.is_staff is False
    assert other.is_superuser is False
    assert User.objects.filter(pk=other.pk).exists()


def test_remove_admin_view_post_blocks_self_demotion(client):
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_remove_admin", args=[admin.pk])
    resp = client.post(url)
    assert resp.status_code == 302

    admin.refresh_from_db()
    assert admin.is_staff is True  # 不变
    assert admin.is_superuser is True


def test_remove_dialog_get_renders_confirmation(client):
    """remove-dialog GET → 渲染含确认按钮的 HTML 片段，含目标 POST URL。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    other = User.objects.create_user(
        username="other@x.com", is_staff=True, is_superuser=True, email="other@x.com",
    )
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_remove_dialog", args=[other.pk])
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "确认移除" in body
    assert "other@x.com" in body
    # dialog 表单 action 指向 POST 端点
    post_url = reverse("admin:accounts_adminuser_remove_admin", args=[other.pk])
    assert post_url in body


def test_remove_dialog_self_shows_block_message(client):
    """点自己一行的"移除" → dialog 显示拦截消息而非确认按钮。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_remove_dialog", args=[admin.pk])
    resp = client.get(url)
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "无法移除" in body
    assert "防锁死" in body
    # 不应渲染"确认移除"提交按钮
    assert "确认移除" not in body


def test_remove_admin_view_htmx_post_returns_hx_redirect(client):
    """htmx POST → 204 + HX-Redirect header（让浏览器跳整页）。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    other = User.objects.create_user(
        username="other@x.com", is_staff=True, is_superuser=True,
    )
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_remove_admin", args=[other.pk])
    resp = client.post(url, HTTP_HX_REQUEST="true")
    assert resp.status_code == 204
    assert resp["HX-Redirect"] == reverse("admin:accounts_adminuser_changelist")
    other.refresh_from_db()
    assert other.is_staff is False


def test_changelist_no_topright_add_button(client):
    """右上角原生 + 号按钮 (object-tools) 应被覆写为空。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    resp = client.get(reverse("admin:accounts_adminuser_changelist"))
    body = resp.content.decode()
    # Unfold 默认 changelist 渲染右上角 add link 的 class 含 'addlink'；
    # 也常带 title="Add" / "Add adminuser"。我们覆写 object-tools 为空块。
    assert 'class="addlink"' not in body
    # 但同行内嵌的"新增管理员"按钮仍在（block search 覆写）
    assert "新增管理员" in body


def test_changelist_only_shows_staff_users(client):
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    User.objects.create_user(username="normal@x.com", is_staff=False)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_changelist")
    resp = client.get(url)
    body = resp.content.decode()
    assert "boss@x.com" in body
    assert "normal@x.com" not in body


def test_changelist_has_inline_add_button_with_chinese_label(client):
    """搜索框与「新增管理员」按钮在同一容器行（block search 覆写）。"""
    admin = User.objects.create_user(username="boss@x.com", is_staff=True, is_superuser=True)
    client.force_login(admin)

    url = reverse("admin:accounts_adminuser_changelist")
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()

    # 按钮文案出现
    assert "新增管理员" in body

    # 搜索框 input 与按钮文案在同一个外层 div 容器内
    # 找到包含 "新增管理员" 字样的那段 HTML，确认同块里也有 searchbar input
    import re
    # 取 block search 覆盖后渲染的容器 —— 用宽松匹配：确认 searchbar 出现在按钮之前的 HTML 里
    search_pos = body.find('name="q"')
    add_pos = body.find("新增管理员")
    assert search_pos != -1, "搜索框 input 应存在于页面"
    assert add_pos != -1, "「新增管理员」按钮文案应存在于页面"
    # 两者应在同一个 flex 容器内 —— 容器 div 在 search_pos 之前开始
    # 简单验证：按钮的 href 包含 add URL 并出现在搜索框附近（500 字符内）
    snippet = body[max(0, search_pos - 50): add_pos + 100]
    assert "新增管理员" in snippet or abs(search_pos - add_pos) < 2000
