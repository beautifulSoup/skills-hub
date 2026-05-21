"""版本下拉 inclusion tag。供 T9 详情页一行 include。"""
from django import template

from skillshub.submit.services import latest_published, published_versions

register = template.Library()


@register.inclusion_tag("version/_dropdown.html")
def version_dropdown(skill, current_version=None):
    """渲染版本下拉。

    Args:
        skill: Skill 实例
        current_version: 当前选中版本（None 时默认 latest）
    """
    versions = list(published_versions(skill))
    if current_version is None:
        current_version = latest_published(skill)
    return {
        "versions": versions,
        "current_version": current_version,
        "latest_id": skill.latest_version_id,  # 整数 PK 或 None
    }
