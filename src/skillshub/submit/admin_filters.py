"""admin 自定义 list_filter。"""
from django.contrib import admin
from django.db.models import Exists, OuterRef

from skillshub.submit.models import SkillVersion


class HasPendingVersionFilter(admin.SimpleListFilter):
    """筛选 skill 是否存在 status=pending_review 的版本。"""

    title = "待审版本"
    parameter_name = "has_pending"

    def lookups(self, request, model_admin):
        return (
            ("yes", "有待审"),
            ("no", "无待审"),
        )

    def queryset(self, request, queryset):
        if self.value() not in {"yes", "no"}:
            return queryset
        pending_exists = SkillVersion.objects.filter(
            skill=OuterRef("pk"),
            status=SkillVersion.STATUS_PENDING_REVIEW,
        )
        annotated = queryset.annotate(_has_pending=Exists(pending_exists))
        return annotated.filter(_has_pending=(self.value() == "yes"))
