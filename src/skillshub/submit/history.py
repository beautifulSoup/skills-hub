"""跨 admin / catalog 复用的 skill 历史事件合并。

把 LogEntry（admin 后台改字段）/ SkillVersion 提交 / ReviewAction 三类
事件合并为统一的时间线 events，按 ts 降序排列。

调用方按需 paginate（admin 用 Django Paginator，catalog 用相同的）。
"""
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType

from skillshub.submit.models import ReviewAction, Skill

_REVIEW_ACTION_LABELS = {
    ReviewAction.ACTION_APPROVE: ("审核通过", "green"),
    ReviewAction.ACTION_REJECT: ("审核拒绝", "red"),
    ReviewAction.ACTION_REQUEST_CHANGES: ("需修改", "yellow"),
    ReviewAction.ACTION_CANCEL_BY_AUTHOR: ("作者取消", "base"),
    ReviewAction.ACTION_AUTO_CANCEL_BY_RESUBMIT: ("重新提交自动取消", "base"),
    ReviewAction.ACTION_DELIST: ("下线 Skill", "red"),
    ReviewAction.ACTION_RELIST: ("上线 Skill", "green"),
    ReviewAction.ACTION_ROLLBACK: ("回退版本", "primary"),
    ReviewAction.ACTION_DISABLE_VERSION: ("下线版本", "red"),
    ReviewAction.ACTION_ENABLE_VERSION: ("上线版本", "green"),
}


def build_skill_events(skill, *, include_admin_log: bool = True) -> list[dict]:
    """合并 skill 的全部历史事件 → 时间线 dict 列表，按 ts 降序。

    Args:
        skill: Skill 实例
        include_admin_log: 是否包含 admin 后台 LogEntry。admin 历史页要包含；
            catalog owner 视图设 False 以隐藏后台改字段记录。
    """
    events: list[dict] = []

    if include_admin_log:
        skill_ct = ContentType.objects.get_for_model(Skill)
        for le in LogEntry.objects.filter(
            content_type=skill_ct, object_id=str(skill.pk),
        ).select_related("user"):
            events.append({
                "ts": le.action_time,
                "actor": le.user.email if le.user else "—",
                "type": "管理后台",
                "type_color": "base",
                "version_no": None,
                "detail": le.get_change_message() or le.object_repr,
            })

    for v in skill.versions.select_related("submitted_by"):
        events.append({
            "ts": v.submitted_at,
            "actor": v.submitted_by.email,
            "type": "提交版本",
            "type_color": "primary",
            "version_no": v.version_no,
            "detail": f"作者提交 v{v.version_no}",
        })

    for ra in ReviewAction.objects.filter(
        version__skill=skill,
    ).select_related("actor", "version"):
        label, color = _REVIEW_ACTION_LABELS.get(
            ra.action, (ra.get_action_display(), "base"),
        )
        events.append({
            "ts": ra.created_at,
            "actor": ra.actor.email,
            "type": label,
            "type_color": color,
            "version_no": ra.version.version_no,
            "detail": ra.reason or "—",
        })

    events.sort(key=lambda e: e["ts"], reverse=True)
    return events
