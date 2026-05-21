"""管理员管理 admin。

把 Django auth.User 包装成"管理员管理"页面：
- 列表只显示 is_staff=True 的用户（管理员）
- 系统两个角色：管理员（=超管）+ 普通用户。新增的管理员自动 is_staff=True
  + is_superuser=True。
- "移除"=软移除：is_staff=False + is_superuser=False；保留 User 行
  （ReviewAction.actor / Skill.created_by / SkillVersion.submitted_by 都 PROTECT
  指向它，硬删会失败）。移除前走 htmx 二次确认 dialog。
- 禁止移除自己（防锁死）。
"""
from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_GET, require_POST


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _htmx_redirect(request, url):
    """htmx 请求成功后跳整页：返回 204 + HX-Redirect；非 htmx fallback 到 302。"""
    if _is_htmx(request):
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = url
        return resp
    return redirect(url)
from unfold.admin import ModelAdmin
from unfold.widgets import UnfoldAdminEmailInputWidget

from skillshub.accounts.models import AdminUser
from skillshub.accounts.whitelist import is_email_allowed


class AdminUserAddForm(forms.ModelForm):
    """新增管理员表单：只问邮箱；存为 is_staff=is_superuser=True + 不可用密码。"""

    email = forms.EmailField(
        label="邮箱",
        widget=UnfoldAdminEmailInputWidget(attrs={"placeholder": "name@company.com"}),
        help_text="该用户后续用此邮箱通过 OTP 登录。",
    )

    class Meta:
        model = AdminUser
        fields = ("email",)

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if not is_email_allowed(email):
            raise forms.ValidationError("该邮箱域名不在白名单内，无法授予管理员权限。")
        return email

    def save(self, commit=True):
        """commit=False 时返回内存中的 User；commit=True 才落库。

        Django admin 的 _changeform_view 先 save(commit=False)，再走
        save_model() 持久化。两次都被调用要保持等价（idempotent）。
        """
        email = self.cleaned_data["email"]
        try:
            user = User.objects.get(username=email)
        except User.DoesNotExist:
            # 新建：OTP 系统不用密码
            user = User(username=email, email=email)
            user.set_unusable_password()
        # 系统就两个角色：管理员=超管。
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.email = email
        if commit:
            user.save()
        self.instance = user
        # 我们的模型无 m2m，但 admin 会调用 save_m2m；提供 no-op
        self.save_m2m = lambda: None
        return user


admin.site.unregister(User)


@admin.register(User)
class _UserAutocompleteAdmin(ModelAdmin):
    """auth.User 隐藏注册 —— 仅给 SkillAdmin.autocomplete_fields 用。

    show_all_applications=False，所以不会出现在侧边栏；
    has_module_permission=False 进一步确保不出现在 admin index 和导航。
    """
    search_fields = ("email", "username")

    def has_module_permission(self, request):
        return False


@admin.register(AdminUser)
class AdminUserAdmin(ModelAdmin):
    """管理员管理（基于 auth.User，queryset 限定 is_staff=True）。"""

    add_form = AdminUserAddForm

    list_display = ("_email", "_last_login", "_date_joined", "_remove_link")
    search_fields = ("email", "username")
    ordering = ("-date_joined",)
    actions = None
    # add 入口已在 changelist 搜索框同行；同时关掉 Unfold 默认在 changelist /
    # change form 右上角 nav-global-side 区渲染的浮动 + 按钮（add_link.html）。
    show_add_link = False

    @admin.display(description="邮箱", ordering="email")
    def _email(self, obj):
        return obj.email or obj.username

    @admin.display(description="上次登录", ordering="last_login")
    def _last_login(self, obj):
        return obj.last_login.strftime("%Y-%m-%d %H:%M") if obj.last_login else "—"

    @admin.display(description="加入时间", ordering="date_joined")
    def _date_joined(self, obj):
        return obj.date_joined.strftime("%Y-%m-%d %H:%M")

    @admin.display(description="操作")
    def _remove_link(self, obj):
        dialog_url = reverse(
            "admin:accounts_adminuser_remove_dialog", args=[obj.pk]
        )
        return format_html(
            '<a href="{}" '
            'hx-get="{}" '
            'hx-target="#modal-content" '
            'hx-select="#dialog" '
            'x-on:htmx:after-on-load="openModal = true" '
            'style="display:inline-flex;align-items:center;gap:4px;'
            'padding:4px 12px;border-radius:6px;'
            'background:#dc2626;color:#ffffff;font-weight:500;'
            'text-decoration:none;font-size:0.85em;cursor:pointer;">'
            '移除管理员</a>',
            dialog_url, dialog_url,
        )

    # —— queryset 限定到 is_staff=True ——
    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_staff=True)

    # —— 新增表单：复用 AdminUserAddForm（fields=email 一栏） ——
    def get_form(self, request, obj=None, change=False, **kwargs):
        if obj is None:
            return AdminUserAddForm
        return super().get_form(request, obj, change=change, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return ((None, {"fields": ("email",)}),)
        # change view 仅展示信息字段；权限位由"新增/移除"按钮管理，不在 change form 暴露
        return (
            (None, {"fields": ("username", "email")}),
            ("时间", {"fields": ("last_login", "date_joined")}),
        )

    readonly_fields = ("username", "last_login", "date_joined")

    def has_add_permission(self, request):
        return request.user.is_superuser or request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        # 列表页用 actions=None 隐藏批量删除；行级"移除"走自定义 URL
        return False

    def save_model(self, request, obj, form, change):
        # change 视图：阻止移除自己的 is_staff（防锁死）
        if change and obj.pk == request.user.pk and not obj.is_staff:
            messages.error(request, "禁止移除自己的管理员权限（防锁死）。")
            obj.is_staff = True
        super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        return _htmx_redirect(request, reverse("admin:accounts_adminuser_changelist"))

    def add_view(self, request, form_url="", extra_context=None):
        """新增管理员页：去掉「保存并继续编辑」「保存并新增」两个按钮，只留 Save。"""
        extra_context = extra_context or {}
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        return super().add_view(request, form_url, extra_context)

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "<int:object_id>/remove-dialog/",
                self.admin_site.admin_view(self.remove_admin_dialog_view),
                name="accounts_adminuser_remove_dialog",
            ),
            path(
                "<int:object_id>/remove-admin/",
                self.admin_site.admin_view(self.remove_admin_view),
                name="accounts_adminuser_remove_admin",
            ),
        ] + urls

    @staticmethod
    @require_GET
    def remove_admin_dialog_view(request, object_id):
        """htmx 渲染二次确认 dialog 片段，由行内"移除"按钮触发。"""
        try:
            user_obj = AdminUser.objects.get(pk=object_id)
        except AdminUser.DoesNotExist:
            return render(request, "admin/accounts/adminuser/remove_dialog.html", {
                "user_obj": None,
                "error_message": "用户不存在。",
            })
        is_self = user_obj.pk == request.user.pk
        return render(request, "admin/accounts/adminuser/remove_dialog.html", {
            "user_obj": user_obj,
            "is_self": is_self,
            "post_url": reverse(
                "admin:accounts_adminuser_remove_admin", args=[object_id]
            ),
        })

    @staticmethod
    @require_POST
    def remove_admin_view(request, object_id):
        """软移除：is_staff=False + is_superuser=False。

        保留 User 行，因为 ReviewAction.actor / Skill.created_by 用 PROTECT FK。
        """
        try:
            user = AdminUser.objects.get(pk=object_id)
        except AdminUser.DoesNotExist:
            messages.error(request, "用户不存在。")
            return _htmx_redirect(request, reverse("admin:accounts_adminuser_changelist"))
        if user.pk == request.user.pk:
            messages.error(request, "禁止移除自己的管理员权限（防锁死）。")
            return _htmx_redirect(request, reverse("admin:accounts_adminuser_changelist"))
        if not user.is_staff:
            messages.info(request, f"{user.email or user.username} 已经不是管理员。")
            return _htmx_redirect(request, reverse("admin:accounts_adminuser_changelist"))
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=["is_staff", "is_superuser"])
        messages.success(request, f"已移除管理员 {user.email or user.username}。")
        return _htmx_redirect(request, reverse("admin:accounts_adminuser_changelist"))
