"""T7 机审 Celery task。

- 单 task 顺序 L1→L2
- 状态守卫（idempotent）：非 pending_machine 直接 return
- 异常兜底：autoretry_for=(Exception,) max=2，用尽后 on_failure 写合成 violation
- 零违规调 services.publish_version；非空直接 update status=pending_review
"""
from __future__ import annotations

import logging
from collections import Counter

from celery import Task, shared_task
from django.db import transaction
from django.utils import timezone

from skillshub.submit.machine_review import l1, l2
from skillshub.submit.machine_review.violations import (
    ENGINE_VERSION,
    L1_INTERNAL_ERROR,
    Violation,
)

logger = logging.getLogger(__name__)


def _build_summary(violations: list[Violation]) -> dict:
    """构造 machine_review_result JSON 摘要。"""
    counts = Counter(v.severity for v in violations)
    l1_passed = not any(v.code.startswith("l1.") for v in violations)
    l2_passed = not any(v.code.startswith("l2.") for v in violations)
    return {
        "scanned_at": timezone.now().isoformat(),
        "l1_passed": l1_passed,
        "l2_passed": l2_passed,
        "violation_count": {
            "error": counts.get("error", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
        },
        "engine_version": ENGINE_VERSION,
    }


class MachineReviewTask(Task):
    """Base task class for machine_review；on_failure 写合成 violation。"""

    autoretry_for = (Exception,)
    max_retries = 2
    retry_backoff = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """重试用尽 / 非 retry 异常 → 写合成 l1.internal_error violation 并转 pending_review。"""
        from skillshub.submit.models import SkillVersion  # 局部 import 防 app loading 循环

        # 优先 kwargs（关键字派发），缺则用 args[0]（位置派发）；兼容混合派发场景
        version_id = (kwargs or {}).get("version_id") or (args[0] if args else None)
        if version_id is None:
            logger.error("machine_review on_failure: 找不到 version_id；args=%r kwargs=%r", args, kwargs)
            return

        synthetic = Violation(
            code=L1_INTERNAL_ERROR, severity="error", location="archive",
            message=f"机审引擎内部异常（{type(exc).__name__}），已转人审。",
        )
        summary = _build_summary([synthetic])
        # 引擎整体崩溃时 l2 也未完成，强制标记为未通过
        summary["l2_passed"] = False
        # 单 query update + status 守卫：仅在仍是 pending_machine 时更新
        updated = SkillVersion.objects.filter(
            pk=version_id,
            status=SkillVersion.STATUS_PENDING_MACHINE,
        ).update(
            status=SkillVersion.STATUS_PENDING_REVIEW,
            violations=[synthetic.asdict()],
            machine_review_result=summary,
        )
        if updated == 0:
            logger.warning(
                "machine_review on_failure: version %s 已不是 pending_machine，跳过更新", version_id
            )


@shared_task(bind=True, base=MachineReviewTask)
def machine_review(self, version_id: int) -> None:
    """异步机审 task。

    Steps：
    1. 状态守卫：非 pending_machine → return
    2. 读 zip bytes
    3. 跑 L1 / L2
    4. 事务内：写 violations + machine_review_result + 状态转移
       - violations 空 → publish_version（reuse T6 service，T7 已放宽接受 pending_machine）
       - 非空 → status = pending_review
    """
    from skillshub.submit.models import SkillVersion
    from skillshub.storage.api import get_storage
    from skillshub.submit.services import publish_version

    try:
        version = SkillVersion.objects.get(pk=version_id)
    except SkillVersion.DoesNotExist:
        logger.warning("machine_review: SkillVersion %s 不存在，跳过", version_id)
        return

    if version.status in SkillVersion.TERMINAL_STATUSES:
        logger.info("machine_review: version %s 已终结（%s），跳过", version_id, version.status)
        return
    if version.status != SkillVersion.STATUS_PENDING_MACHINE:
        logger.info("machine_review: version %s 状态 %s 非 pending_machine，跳过", version_id, version.status)
        return

    content = get_storage().get(version.file_path)

    l1_violations = l1.run(content, version)
    l2_violations = l2.run(content)
    violations = l1_violations + l2_violations
    summary = _build_summary(violations)

    with transaction.atomic():
        # 重读 + 锁；防与 cancel 竞争
        v = SkillVersion.objects.select_for_update().get(pk=version_id)
        if v.status != SkillVersion.STATUS_PENDING_MACHINE:
            # 跑机审期间被 cancel；外层 atomic 自动回滚未提交的字段写入
            logger.info(
                "machine_review: version %s 跑审期间状态变为 %s，原子块回滚",
                version_id, v.status,
            )
            return
        v.violations = [item.asdict() for item in violations]
        v.machine_review_result = summary
        if not violations:
            # publish_version 内自己开 atomic + select_for_update + 三赋值；
            # 这里先把 violations / machine_review_result 落盘
            v.save(update_fields=["violations", "machine_review_result"])
            publish_version(v)
        else:
            v.status = SkillVersion.STATUS_PENDING_REVIEW
            v.save(update_fields=["status", "violations", "machine_review_result"])
