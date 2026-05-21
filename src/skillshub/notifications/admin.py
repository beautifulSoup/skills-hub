"""Notifications Django Admin（精简：unfold ModelAdmin，不定制）。"""
from django.contrib import admin
from unfold.admin import ModelAdmin

from skillshub.notifications.models import FailedEmail


@admin.register(FailedEmail)
class FailedEmailAdmin(ModelAdmin):
    list_display = ("_to", "subject_template", "attempts", "_created_at", "_resolved_at")
    readonly_fields = (
        "to", "subject_template", "body_text_template", "body_html_template",
        "context", "last_error", "attempts", "created_at",
    )

    @admin.display(description="收件人")
    def _to(self, obj):
        return ", ".join(obj.to) if obj.to else "—"

    @admin.display(description="失败时间", ordering="created_at")
    def _created_at(self, obj):
        return obj.created_at.strftime("%Y-%m-%d %H:%M")

    @admin.display(description="已解决", ordering="resolved_at")
    def _resolved_at(self, obj):
        return obj.resolved_at.strftime("%Y-%m-%d %H:%M") if obj.resolved_at else "—"
