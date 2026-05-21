"""Admin 仪表盘统计 inclusion tag。

供 templates/admin/index.html 一次性拉全站统计数。所有查询都很轻，没有
索引压力（count + 单 Sum aggregate）。
"""
from django import template
from django.contrib.auth.models import User
from django.db.models import Sum

from skillshub.submit.models import Skill, SkillVersion

register = template.Library()


@register.simple_tag
def admin_dashboard_stats() -> dict:
    """返回 admin index 仪表盘的 4 项指标。"""
    return {
        "pending_skills": SkillVersion.objects.filter(
            status=SkillVersion.STATUS_PENDING_REVIEW,
        ).count(),
        "total_skills": Skill.objects.count(),
        "total_installs": Skill.objects.aggregate(
            total=Sum("install_count"),
        )["total"] or 0,
        "total_users": User.objects.count(),
    }
