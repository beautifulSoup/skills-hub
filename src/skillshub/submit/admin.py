"""Admin 注册 Skill + SkillVersion + ReviewAction (T8)。

T6: SkillAdmin list_display 加 latest_version + version_count；
     latest_version 移出 readonly（人工干预口子）。
     SkillVersionAdmin list_filter 加 published_at；published_at readonly。
T8: SkillVersionAdmin 加自定义 review/file URL；ReviewAction 注册只读 admin。
"""
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.widgets import RelatedFieldWidgetWrapper
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin
from unfold.widgets import UnfoldAdminTextareaWidget, UnfoldAdminTextInputWidget

from skillshub.submit.admin_filters import HasPendingVersionFilter
from skillshub.submit.admin_views import (
    bulk_listing_view, delete_dialog_view, disable_version_view,
    enable_version_view, file_download_view, file_preview_view, file_view,
    listing_dialog_view, review_view, rollback_view,
    version_action_dialog_view, version_detail_view, version_view,
    versions_view, zip_download_view,
)
from skillshub.submit.models import PendingSkillVersion, ReviewAction, Skill, SkillVersion


class SkillAdminForm(forms.ModelForm):
    """Skill change view 自定义表单。

    - detailed_description: 把 latest_version.readme 暴露为可编辑字段（必填，
      与用户端 submit 表单一致），save_model 时写回 latest_version。
    - tags: 覆盖 JSONField 的默认 widget；展示/输入皆为逗号分隔，与用户端
      submit 表单一致。
    """

    detailed_description = forms.CharField(
        label="详细描述",
        widget=UnfoldAdminTextareaWidget(attrs={"rows": 12}),
        required=True,
        help_text="最新版本的 readme（Markdown）。保存后会写回 latest_version。",
    )
    tags = forms.CharField(
        label="标签",
        required=False,
        widget=UnfoldAdminTextInputWidget(),
        help_text="逗号分隔，如 code-review,python",
    )

    class Meta:
        model = Skill
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst and inst.pk:
            self.initial["tags"] = ", ".join(inst.tags or [])
            if inst.latest_version_id:
                self.initial["detailed_description"] = inst.latest_version.readme
            else:
                # 无 published 最新版本：回退展示最近一次提交版本的 readme（任意状态，
                # 含待审/需修改/已拒/已取消，只读、无可写回目标），便于审核员查看说明。
                fallback = inst.versions.order_by("-submitted_at").first()
                self.fields["detailed_description"].disabled = True
                self.fields["detailed_description"].required = False
                if fallback is not None:
                    self.initial["detailed_description"] = fallback.readme
                    self.fields["detailed_description"].help_text = (
                        f"无已发布版本；下方为最近版本 v{fallback.version_no}"
                        f"（{fallback.get_status_display()}）的 readme，只读。"
                    )
                else:
                    self.fields["detailed_description"].help_text = "暂无任何版本"

    def clean_tags(self) -> list[str]:
        raw = self.cleaned_data.get("tags", "")
        if not raw:
            return []
        # 同时兼容中文全角逗号 ，
        raw = raw.replace("，", ",")
        return [t.strip() for t in raw.split(",") if t.strip()]


@admin.register(Skill)
class SkillAdmin(ModelAdmin):
    form = SkillAdminForm
    autocomplete_fields = ("created_by",)

    list_display = (
        "name", "_type", "_is_listed_badge", "_latest_version",
        "_version_count", "_pending_count",
        "_created_by", "_created_at", "_install_count",
        "_detail_link",
    )
    list_filter = ("is_listed", HasPendingVersionFilter)
    search_fields = ("name", "description", "created_by__email")

    @admin.display(description="类型", ordering="type")
    def _type(self, obj):
        return obj.get_type_display()

    @admin.display(description="上线", boolean=True, ordering="is_listed")
    def _is_listed_badge(self, obj):
        return obj.is_listed

    @admin.display(description="最新版本", ordering="latest_version")
    def _latest_version(self, obj):
        return obj.latest_version

    @admin.display(description="版本数")
    def _version_count(self, obj):
        return obj.versions.count()

    @admin.display(description="待审")
    def _pending_count(self, obj):
        return obj.versions.filter(
            status=SkillVersion.STATUS_PENDING_REVIEW
        ).count()

    @admin.display(description="创建人", ordering="created_by")
    def _created_by(self, obj):
        return obj.created_by.email

    @admin.display(description="创建时间", ordering="created_at")
    def _created_at(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    @admin.display(description="⚡ 安装次数", ordering="install_count")
    def _install_count(self, obj):
        return obj.install_count

    @admin.display(description="详情")
    def _detail_link(self, obj):
        url = reverse("admin:submit_skill_change", args=[obj.pk])
        return format_html(
            '<a href="{}" style="color:#9333ea;text-decoration:underline;">详情</a>',
            url,
        )

    actions = None

    def get_actions(self, request):
        return {}

    def has_add_permission(self, request):
        return False

    # §v2.5 — 计算字段（只读显示）

    @admin.display(description="版本清单")
    def _version_summary(self, obj):
        """显示最新版本号 + 待审版本数 + 跳「版本列表」链接。

        即使无 published 最新版本（latest_version is None），只要有任意版本就给出
        「查看全部版本」入口，并标注待审版本数——避免待审 / 未通过版本在变更页隐身。
        """
        from django.urls import reverse as _reverse
        from django.utils.html import format_html as _format_html

        total = obj.versions.count()
        if total == 0:
            return "暂无版本"

        pending = obj.versions.filter(
            status=SkillVersion.STATUS_PENDING_REVIEW
        ).count()
        if obj.latest_version_id:
            head = _format_html("最新版本：<strong>v{}</strong>", obj.latest_version.version_no)
        else:
            head = _format_html("<strong>无已发布版本</strong>")
        pending_note = (
            _format_html("&nbsp;·&nbsp;<span style=\"color:#b45309;\">{} 个待审</span>", pending)
            if pending else ""
        )
        url = _reverse("admin:submit_skill_versions", args=[obj.id])
        link = _format_html(
            '&nbsp;&nbsp;<a href="{}" '
            'style="display:inline-flex;align-items:center;gap:4px;'
            'padding:4px 12px;border-radius:6px;'
            'background:#9333ea;color:#ffffff;font-weight:500;'
            'text-decoration:none;font-size:0.85em;">'
            '查看全部版本（{}）→</a>',
            url, total,
        )
        return _format_html("{}{}{}", head, pending_note, link)

    @admin.display(description="上下线状态")
    def _is_listed_inline(self, obj):
        """is_listed 状态徽章。上下线按钮在表单底部 Delete 按钮旁。"""
        from django.utils.html import format_html as _format_html
        status_label = "上线" if obj.is_listed else "已下线"
        status_color = "#16a34a" if obj.is_listed else "#b91c1c"
        return _format_html(
            '<strong style="color:{}">{}</strong>',
            status_color, status_label,
        )

    readonly_fields = (
        "name", "type",
        "_version_summary",
        "_is_listed_inline",
        "created_at", "install_count",
    )

    fieldsets = (
        (None, {
            "fields": (
                "name",
                "type",
                "description",
                "detailed_description",
                "tags",
                "_version_summary",
                "created_by",
                "_is_listed_inline",
                "created_at",
                "install_count",
            ),
        }),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # 把表单里的 detailed_description 写回 latest_version.readme
        new_readme = form.cleaned_data.get("detailed_description")
        if (
            new_readme is not None
            and obj.latest_version_id
            and obj.latest_version.readme != new_readme
        ):
            obj.latest_version.readme = new_readme
            obj.latest_version.save(update_fields=["readme"])

    # —— 级联删除：SkillAdmin 自己接管整条清理 ——
    # ReviewAction 通过 PROTECT 指向 SkillVersion，会阻断 cascade；先手动
    # 删掉 ReviewAction 再让 super 走 Skill→SkillVersion 的标准 cascade。
    # 同时清空 get_deleted_objects 的 perms_needed / protected，
    # 让没有 submit.delete_skillversion 权限的 staff 也能从 Skill 端删整棵树。
    # 直接的 SkillVersion / ReviewAction 删除入口仍然没有暴露给 UI。

    def delete_model(self, request, obj):
        with transaction.atomic():
            ReviewAction.objects.filter(version__skill=obj).delete()
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            ReviewAction.objects.filter(version__skill__in=queryset).delete()
            super().delete_queryset(request, queryset)

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, _perms_needed, _protected = (
            super().get_deleted_objects(objs, request)
        )
        return deleted_objects, model_count, set(), []

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # Django 在 formfield_for_dbfield 里先调 formfield_for_foreignkey 再
        # 包 RelatedFieldWidgetWrapper（Unfold 用其模板渲染右侧 ⋮ 菜单）。
        # 在更晚的 formfield_for_dbfield 里拆掉 wrapper，才不会被外层重新包回。
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if (
            db_field.name == "created_by"
            and formfield is not None
            and isinstance(formfield.widget, RelatedFieldWidgetWrapper)
        ):
            formfield.widget = formfield.widget.widget
        return formfield

    def response_post_save_change(self, request, obj):
        """保存成功后留在详情页，不要跳回列表。
        success 消息由 super().response_change(...) 已加入 messages，
        顶部 Unfold messages 组件会渲染绿色 banner。
        """
        return HttpResponseRedirect(
            reverse(
                f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                args=[obj.pk],
            )
        )

    def render_change_form(self, request, context, *args, **kwargs):
        """POST 提交后表单未通过校验 → 在顶部加一条红色 messages."""
        if request.method == "POST":
            adminform = context.get("adminform")
            if adminform is not None and adminform.form.errors:
                messages.error(request, "保存失败，请检查表单。")
        return super().render_change_form(request, context, *args, **kwargs)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_continue"] = False
        extra_context["show_save_and_add_another"] = False
        # submit_line.html 用：上下线 / 删除按钮挂在底部，点击触发 modal。
        # mark_safe 避免 Django 把 " 转义成 &quot;，否则浏览器解析后 hx-target
        # 的值会带字面引号，htmx 拿去 querySelectorAll 会抛 invalid selector。
        def _modal_attrs(url: str) -> str:
            return mark_safe(
                f'hx-get="{url}" '
                'hx-target="#modal-content" '
                'hx-select="#dialog" '
                'x-on:htmx:after-on-load="openModal = true"'
            )

        listing_url = reverse(
            "admin:submit_skill_listing_dialog", args=[object_id]
        )
        delete_url = reverse(
            "admin:submit_skill_delete_dialog", args=[object_id]
        )
        extra_context["listing_dialog_url"] = listing_url
        extra_context["listing_dialog_attrs"] = _modal_attrs(listing_url)
        extra_context["delete_dialog_url"] = delete_url
        extra_context["delete_dialog_attrs"] = _modal_attrs(delete_url)
        return super().change_view(request, object_id, form_url, extra_context)

    def history_view(self, request, object_id, extra_context=None):
        """合并历史时间线：LogEntry + SkillVersion 提交 + ReviewAction，
        Paginator 分页 20 / 页。
        """
        from django.core.paginator import Paginator
        from django.shortcuts import get_object_or_404
        from django.template.response import TemplateResponse

        from skillshub.submit.admin_views import _admin_context
        from skillshub.submit.history import build_skill_events

        skill = get_object_or_404(Skill, pk=object_id)
        events = build_skill_events(skill)

        paginator = Paginator(events, 20)
        page_obj = paginator.get_page(request.GET.get("page"))

        context = _admin_context(request, {
            "title": f"{skill.name} 历史",
            "original": skill,
            "opts": Skill._meta,
            "events": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_count": paginator.count,
            "breadcrumb_extra": [{"title": "历史"}],
            "back_url": reverse(
                "admin:submit_skill_change", args=[object_id]
            ),
        })
        if extra_context:
            context.update(extra_context)
        return TemplateResponse(
            request, "admin/submit/skill/object_history.html", context
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "bulk-listing/",
                self.admin_site.admin_view(bulk_listing_view),
                name="submit_skill_bulk_listing",
            ),
            path(
                "<int:object_id>/listing-dialog/",
                self.admin_site.admin_view(listing_dialog_view),
                name="submit_skill_listing_dialog",
            ),
            path(
                "<int:object_id>/delete-dialog/",
                self.admin_site.admin_view(delete_dialog_view),
                name="submit_skill_delete_dialog",
            ),
            path(
                "<int:object_id>/versions/",
                self.admin_site.admin_view(versions_view),
                name="submit_skill_versions",
            ),
            path(
                "<int:object_id>/rollback/",
                self.admin_site.admin_view(rollback_view),
                name="submit_skill_rollback",
            ),
            path(
                "version/<int:object_id>/disable/",
                self.admin_site.admin_view(disable_version_view),
                name="submit_version_disable",
            ),
            path(
                "version/<int:object_id>/enable/",
                self.admin_site.admin_view(enable_version_view),
                name="submit_version_enable",
            ),
            path(
                "version/<int:object_id>/detail/",
                self.admin_site.admin_view(version_detail_view),
                name="submit_version_detail",
            ),
            path(
                "version/<int:object_id>/dialog/<str:op>/",
                self.admin_site.admin_view(version_action_dialog_view),
                name="submit_version_action_dialog",
            ),
        ]
        return custom + urls


@admin.register(SkillVersion)
class SkillVersionAdmin(ModelAdmin):
    list_display = (
        "_skill", "version_no", "_status", "_submitted_at",
        "_published_at", "_submitted_by", "_review_link",
    )
    list_filter = ("status", "published_at")
    ordering = ("submitted_at",)  # 待审 FIFO
    readonly_fields = ("submitted_at", "sha256", "file_path", "published_at")

    @admin.display(description="Skill", ordering="skill")
    def _skill(self, obj):
        return obj.skill.name

    @admin.display(description="状态", ordering="status")
    def _status(self, obj):
        return obj.get_status_display()

    @admin.display(description="提交时间", ordering="submitted_at")
    def _submitted_at(self, obj):
        return obj.submitted_at.strftime("%Y-%m-%d %H:%M")

    @admin.display(description="发布时间", ordering="published_at")
    def _published_at(self, obj):
        return obj.published_at.strftime("%Y-%m-%d %H:%M") if obj.published_at else "—"

    @admin.display(description="提交人", ordering="submitted_by")
    def _submitted_by(self, obj):
        return obj.submitted_by.email

    @admin.display(description="审核")
    def _review_link(self, obj):
        url = reverse("admin:submit_skillversion_review", args=[obj.id])
        return format_html('<a href="{}">审核 →</a>', url)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:object_id>/review/",
                self.admin_site.admin_view(review_view),
                name="submit_skillversion_review",
            ),
            path(
                "<int:object_id>/file/",
                self.admin_site.admin_view(file_view),
                name="submit_skillversion_file",
            ),
            path(
                "<int:object_id>/zip-download/",
                self.admin_site.admin_view(zip_download_view),
                name="submit_skillversion_zip_download",
            ),
            path(
                "<int:object_id>/file-download/",
                self.admin_site.admin_view(file_download_view),
                name="submit_skillversion_file_download",
            ),
            path(
                "<int:object_id>/file-preview/",
                self.admin_site.admin_view(file_preview_view),
                name="submit_skillversion_file_preview",
            ),
            path(
                "<int:object_id>/view/",
                self.admin_site.admin_view(version_view),
                name="submit_skillversion_view",
            ),
        ]
        return custom + urls


@admin.register(PendingSkillVersion)
class PendingSkillVersionAdmin(SkillVersionAdmin):
    """Skill 审核入口（proxy）：只显示 status=pending_review 的版本。

    复用 SkillVersionAdmin 的 list_display / get_urls；通过覆写 get_queryset
    限制可见行。审核链接（_review_link）使用既有 admin:submit_skillversion_review
    URL name（继承自 SkillVersionAdmin 即可，无需新注册）。
    """

    # 只有一个状态可看（pending_review），筛选按钮没意义
    list_filter = ()
    # 按 Skill 名称搜索（与 SkillAdmin 一致）
    search_fields = ("skill__name",)
    # 去掉行首复选框 + 顶部批量操作（含 delete_selected）
    actions = None

    def get_actions(self, request):
        return {}

    @admin.display(description="审核")
    def _review_link(self, obj):
        url = reverse("admin:submit_skillversion_review", args=[obj.id])
        return format_html(
            '<a href="{}" '
            'style="display:inline-flex;align-items:center;gap:4px;'
            'padding:4px 12px;border-radius:6px;'
            'background:#9333ea;color:#ffffff;font-weight:500;'
            'text-decoration:none;font-size:0.85em;">'
            '审核 →</a>',
            url,
        )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            status=SkillVersion.STATUS_PENDING_REVIEW
        )

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        # 不调用 SkillVersionAdmin.get_urls() — 否则 submit_skillversion_review
        # / submit_skillversion_file URL name 会被重新注册到 pendingskillversion
        # 前缀下，shadowing 掉 T8 原本注册在 /skillversion/ 前缀的 URL。
        # 直接跳到 unfold.admin.ModelAdmin.get_urls()。
        return super(SkillVersionAdmin, self).get_urls()


# ReviewAction 不再注册到 admin —— 改在 SkillAdmin.history_view 内聚合展示。
