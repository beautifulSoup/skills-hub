"""Skill 提交业务逻辑。

核心设计决策：
- D-T5-3: SELECT FOR UPDATE 保证并发约束（每 skill 最多 1 条非终结 version）
- D-T5-3: transaction.on_commit 防机审 task 在事务未提交时跑
"""
import hashlib
import logging
import secrets

from django.conf import settings as django_settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.db.models import Max

from skillshub.notifications.api import send_review_result_email
from skillshub.storage.api import get_storage
from skillshub.submit.models import ReviewAction, Skill, SkillVersion
from skillshub.submit.tasks import machine_review
from skillshub.submit.validators import validate_skill_zip

logger = logging.getLogger(__name__)


class ConcurrentSubmissionError(Exception):
    """Skill 已有非终结版本，拒绝并发提交。"""


class SkillNameConflictError(Exception):
    """同名 Skill 已被他人创建，拒绝占用他人名称。"""


def create_skill_version(
    submitter,
    name: str,
    description: str,
    readme: str,
    tags: list,
    content_bytes: bytes,
) -> SkillVersion:
    """创建新 SkillVersion，保证并发约束 + 内容落 Storage + 入队机审 task。

    Steps（均在 atomic 事务内）：
      1. validate_skill_zip
      2. SELECT FOR UPDATE get_or_create Skill
      3. 校验无非终结 version
      4. 计算 next version_no
      5. 计算 sha256
      6. 落 Storage
      7. 创建 SkillVersion
      8. transaction.on_commit 入队 machine_review
    """
    # Step 1: zip 校验（在事务外做，避免持有锁时做 I/O）
    ok, err = validate_skill_zip(content_bytes)
    if not ok:
        raise ValidationError(err)

    with transaction.atomic():
        # Step 2: 锁 Skill 行，防并发 race
        skill, created = Skill.objects.select_for_update().get_or_create(
            name=name,
            defaults={
                "description": description,
                "tags": tags,
                "created_by": submitter,
            },
        )
        # 同名 skill 已被他人创建 → 拒绝占用（name 是公开 URL 锚，且 owner 视图
        # 按 created_by 归属，他人占用会导致提交者无法查看自己的提交）。
        if not created and skill.created_by_id != submitter.id:
            raise SkillNameConflictError(
                f"名称 '{name}' 已被他人占用，请换一个名称。"
            )

        # get_or_create 在已存在时不会应用 defaults，导致后续版本提交时填的
        # description / tags 永远写不进 Skill。每次提交都用当前版本的值同步。
        if not created:
            skill.description = description
            skill.tags = tags
            skill.save(update_fields=["description", "tags"])

        # Step 3: 并发约束分流（T8 R-7）
        #   pending_machine / pending_review → 拒绝（R-3/R-14 at-most-one-in-flight）
        #   changes_requested → 自动 cancel 旧版 + ReviewAction，再继续
        active_versions = list(
            skill.versions.select_for_update()
            .filter(status__in=SkillVersion.NON_TERMINAL_STATUSES)
        )
        in_flight = [
            v for v in active_versions
            if v.status in {
                SkillVersion.STATUS_PENDING_MACHINE,
                SkillVersion.STATUS_PENDING_REVIEW,
            }
        ]
        if in_flight:
            raise ConcurrentSubmissionError(
                f"Skill '{name}' 已有待审版本，请等待审核完成后再提交。"
            )

        # changes_requested 旧版自动 cancel + 写审计
        for old in active_versions:
            if old.status == SkillVersion.STATUS_CHANGES_REQUESTED:
                old.status = SkillVersion.STATUS_CANCELLED
                old.save(update_fields=["status"])
                ReviewAction.objects.create(
                    version=old,
                    actor=submitter,
                    action=ReviewAction.ACTION_AUTO_CANCEL_BY_RESUBMIT,
                    reason="作者基于 changes_requested 复提，旧版自动取消。",
                )

        # Step 4: next version_no
        existing_max = skill.versions.aggregate(max_no=Max("version_no"))["max_no"]
        next_no = (existing_max or 0) + 1

        # Step 5: sha256
        sha256 = hashlib.sha256(content_bytes).hexdigest()

        # Step 6: 落 Storage
        file_path = f"skills/{skill.name}/v{next_no}.zip"
        get_storage().save(file_path, content_bytes)

        # Step 7: 创建 SkillVersion
        version = SkillVersion.objects.create(
            skill=skill,
            version_no=next_no,
            file_path=file_path,
            sha256=sha256,
            readme=readme,
            status=SkillVersion.STATUS_PENDING_MACHINE,
            submitted_by=submitter,
        )

        # Step 8: 事务提交后入队机审（避免 task 在事务未提交时跑）
        transaction.on_commit(lambda: machine_review.delay(version.id))

    return version


def cancel_version(user, version: SkillVersion) -> None:
    """作者取消自己的非终结版本。

    Raises:
        PermissionDenied: 非作者操作
        ValueError: version 已处于终结态
    """
    # 先校验作者（不在事务内，快速 fail）
    if version.submitted_by_id != user.id:
        raise PermissionDenied("只有版本作者可以取消该版本。")

    with transaction.atomic():
        # 重读 version + 行锁，防并发 double-cancel
        version = SkillVersion.objects.select_for_update().get(pk=version.pk)

        if version.status not in SkillVersion.NON_TERMINAL_STATUSES:
            raise ValueError(f"已终结状态 '{version.status}' 不可取消。")

        version.status = SkillVersion.STATUS_CANCELLED
        version.save(update_fields=["status"])


class InvalidStateError(Exception):
    """version 当前状态不允许此操作（如状态不在 PUBLISHABLE_FROM 时调 publish_version）。"""


class InvalidOperationError(Exception):
    """业务规则违反（如重复下线 / cross-skill rollback / 无 latest_version 时下线）。

    与 InvalidStateError 区别：InvalidStateError 是状态机层面（pending→published
    路径上的违反），InvalidOperationError 是业务层面（参数语义不合规）。
    """


PUBLISHABLE_FROM = {
    SkillVersion.STATUS_PENDING_MACHINE,   # T7 自动发布（机审零违规）
    SkillVersion.STATUS_PENDING_REVIEW,    # T8 人审 approve
}


def publish_version(version: SkillVersion) -> None:
    """T7 机审零违规 + T8 人审 approve 的共同发布入口。

    Caller:
    - T7 machine_review task：传入 status==pending_machine 且 violations==[]
    - T8 approve action：传入 status==pending_review

    事务原子地：
    - select_for_update 重读
    - 校验 version.status in PUBLISHABLE_FROM
    - 设 status = published, published_at = now
    - 设 version.skill.latest_version = version

    Raises:
        InvalidStateError: status 不在 PUBLISHABLE_FROM
    """
    with transaction.atomic():
        version = SkillVersion.objects.select_for_update().get(pk=version.pk)

        if version.status not in PUBLISHABLE_FROM:
            raise InvalidStateError(
                f"version {version.pk} 状态为 '{version.status}'，"
                f"仅 {sorted(PUBLISHABLE_FROM)} 可 publish。"
            )

        # T10: publish 时生成 download_token (永久, 不限次)
        if version.download_token is None:
            version.download_token = secrets.token_urlsafe(16)

        version.status = SkillVersion.STATUS_PUBLISHED
        version.published_at = timezone.now()
        version.save(update_fields=["status", "published_at", "download_token"])

        skill = version.skill
        skill.latest_version = version
        skill.save(update_fields=["latest_version"])


def published_versions(skill: Skill):
    """返回 skill 下所有「用户可见」的 published 版本，按 version_no 倒序。

    `is_available=False` 的版本（管理员手动下线）不再对最终用户暴露 ——
    catalog 版本下拉、install 选择等用户端入口都基于这个查询。
    """
    return skill.versions.filter(
        status=SkillVersion.STATUS_PUBLISHED,
        is_available=True,
    ).order_by("-version_no")


def latest_published(skill: Skill) -> SkillVersion | None:
    """返回 skill.latest_version（FK 解引用），未发布过返回 None。"""
    return skill.latest_version


REVIEW_FROM = {SkillVersion.STATUS_PENDING_REVIEW}


def _build_review_url(version: SkillVersion) -> str:
    """拼绝对 URL 给邮件 review_url 字段。"""
    base = getattr(django_settings, "BASE_URL", "http://localhost:8000").rstrip("/")
    path = reverse("admin:submit_skillversion_review", args=[version.id])
    return f"{base}{path}"


def _send_review_email_safe(
    *, version: SkillVersion, decision: str, reason: str
) -> None:
    """调 T11 邮件 API；broker 入队失败不回滚（依赖 FailedEmail 兜底）。"""
    try:
        send_review_result_email(
            to=version.submitted_by.email,
            decision=decision,
            skill_name=version.skill.name,
            version_no=version.version_no,
            reason=reason,
            review_url=_build_review_url(version),
        )
    except Exception:
        logger.error(
            "send_review_result_email failed for version=%s decision=%s",
            version.pk, decision,
            exc_info=True,
        )


def approve_version(version: SkillVersion, *, actor, reason: str = "") -> None:
    """T8 admin approve 入口。

    复用 publish_version 完成状态机转移（pending_review → published +
    设 published_at + 维护 skill.latest_version）。

    Raises:
        InvalidStateError: version 不在 pending_review。
    """
    with transaction.atomic():
        v = SkillVersion.objects.select_for_update().get(pk=version.pk)
        if v.status not in REVIEW_FROM:
            raise InvalidStateError(
                f"version {v.pk} 状态为 '{v.status}'，approve 仅允许 pending_review。"
            )
        # publish_version 内部再做一次 select_for_update + 状态守卫（幂等安全）
        publish_version(v)
        ReviewAction.objects.create(
            version=v, actor=actor, action=ReviewAction.ACTION_APPROVE, reason=reason
        )

    # 邮件在事务外发（避免 broker 卡住事务），失败不回滚
    _send_review_email_safe(version=version, decision="approve", reason=reason)


def _simple_review_action(
    version: SkillVersion,
    *,
    actor,
    target_status: str,
    action_const: str,
    decision_label: str,
    reason: str,
) -> None:
    """reject / request_changes 共用：状态守卫 + setattr + ReviewAction + email。

    Args:
        target_status: 目标状态（STATUS_REJECTED 或 STATUS_CHANGES_REQUESTED）。
        action_const: ReviewAction.ACTION_* 常量。
        decision_label: 邮件 decision 字段（"reject" 或 "changes_requested"）。
        reason: 必填，空字符串或空白抛 ValueError。
    """
    if not reason or not reason.strip():
        raise ValueError(f"{decision_label} 需要非空 reason。")

    with transaction.atomic():
        v = SkillVersion.objects.select_for_update().get(pk=version.pk)
        if v.status not in REVIEW_FROM:
            raise InvalidStateError(
                f"version {v.pk} 状态为 '{v.status}'，"
                f"{decision_label} 仅允许 pending_review。"
            )
        v.status = target_status
        v.save(update_fields=["status"])
        ReviewAction.objects.create(
            version=v, actor=actor, action=action_const, reason=reason
        )

    # 邮件在事务外发（避免 broker 卡住事务），失败不回滚
    _send_review_email_safe(version=version, decision=decision_label, reason=reason)


def reject_version(version: SkillVersion, *, actor, reason: str) -> None:
    """T8 admin reject 入口。reason 必填。"""
    _simple_review_action(
        version,
        actor=actor,
        target_status=SkillVersion.STATUS_REJECTED,
        action_const=ReviewAction.ACTION_REJECT,
        decision_label="reject",
        reason=reason,
    )


def request_changes_version(version: SkillVersion, *, actor, reason: str) -> None:
    """T8 admin request_changes 入口。reason 必填。"""
    _simple_review_action(
        version,
        actor=actor,
        target_status=SkillVersion.STATUS_CHANGES_REQUESTED,
        action_const=ReviewAction.ACTION_REQUEST_CHANGES,
        decision_label="changes_requested",
        reason=reason,
    )


# ============================================================
# admin-skill-management: 人为干预 service
# ============================================================

def _require_reason(reason: str, *, op: str) -> str:
    """统一 reason 校验：必填、strip 后非空。返回 stripped 值。"""
    if not reason or not reason.strip():
        raise ValueError(f"{op} 需要非空 reason。")
    return reason.strip()


def delist_skill(skill: Skill, *, actor, reason: str) -> None:
    """admin 下线 skill：is_listed True→False，写 ReviewAction(delist)。

    Raises:
        ValueError: reason 为空。
        InvalidOperationError: skill 无 latest_version，或已经下线。
    """
    reason = _require_reason(reason, op="delist")

    with transaction.atomic():
        s = Skill.objects.select_for_update().get(pk=skill.pk)
        if s.latest_version_id is None:
            raise InvalidOperationError(
                f"skill '{s.name}' 没有 latest_version，不可下线。"
            )
        if s.is_listed is False:
            raise InvalidOperationError(f"skill '{s.name}' 已下线。")
        s.is_listed = False
        s.save(update_fields=["is_listed"])
        ReviewAction.objects.create(
            version_id=s.latest_version_id,
            actor=actor,
            action=ReviewAction.ACTION_DELIST,
            reason=reason,
        )


def relist_skill(skill: Skill, *, actor, reason: str) -> None:
    """admin 上线 skill：is_listed False→True，写 ReviewAction(relist)。

    Raises:
        ValueError: reason 为空。
        InvalidOperationError: 已上线。
    """
    reason = _require_reason(reason, op="relist")

    with transaction.atomic():
        s = Skill.objects.select_for_update().get(pk=skill.pk)
        if s.latest_version_id is None:
            raise InvalidOperationError(
                f"skill '{s.name}' 没有 latest_version，不可上线。"
            )
        if s.is_listed is True:
            raise InvalidOperationError(f"skill '{s.name}' 已上线。")
        s.is_listed = True
        s.save(update_fields=["is_listed"])
        ReviewAction.objects.create(
            version_id=s.latest_version_id,
            actor=actor,
            action=ReviewAction.ACTION_RELIST,
            reason=reason,
        )


def rollback_skill(
    skill: Skill, target_version: SkillVersion, *, actor, reason: str
) -> None:
    """admin 把 skill.latest_version 指向 target_version。

    Raises:
        ValueError: reason 为空。
        InvalidOperationError: target 不属于该 skill 或已经是当前 latest。
        InvalidStateError: target.status != published（lock 内再校验一次）。
    """
    reason = _require_reason(reason, op="rollback")

    if target_version.skill_id != skill.id:
        raise InvalidOperationError(
            f"target version {target_version.pk} 不属于 skill '{skill.name}'。"
        )

    with transaction.atomic():
        s = Skill.objects.select_for_update().get(pk=skill.pk)
        # 在锁内重读 target_version，防止 status 在快照读后被改写
        target = SkillVersion.objects.select_for_update().get(pk=target_version.pk)
        if target.status != SkillVersion.STATUS_PUBLISHED:
            raise InvalidStateError(
                f"target version {target.pk} 状态为 '{target.status}'，"
                f"rollback 仅允许 published 版本。"
            )
        if s.latest_version_id == target.id:
            raise InvalidOperationError(
                f"target version 已经是 skill '{s.name}' 的当前 latest。"
            )
        s.latest_version_id = target.id
        s.save(update_fields=["latest_version"])
        ReviewAction.objects.create(
            version_id=target.id,
            actor=actor,
            action=ReviewAction.ACTION_ROLLBACK,
            reason=reason,
        )


def disable_version(version: SkillVersion, *, actor, reason: str) -> None:
    """admin 下线单个版本：is_available True→False，写 ReviewAction(disable_version)。

    与 skill 级 delist 正交：disabled 版本即便 skill is_listed=True，用户也看不到。

    若被下线的恰是 skill.latest_version，自动把 latest_version 回退到上一个
    可用（status=published 且 is_available=True）版本；没有则置 None（catalog 隐藏）。
    避免「下线当前版本后 latest 仍指向已下线版本、公开侧直接 404」。

    Raises:
        ValueError: reason 为空。
        InvalidOperationError: 已 disabled。
    """
    reason = _require_reason(reason, op="disable_version")

    with transaction.atomic():
        v = SkillVersion.objects.select_for_update().get(pk=version.pk)
        if v.is_available is False:
            raise InvalidOperationError(
                f"version {v.pk} 已下线。"
            )
        v.is_available = False
        v.save(update_fields=["is_available"])
        ReviewAction.objects.create(
            version=v,
            actor=actor,
            action=ReviewAction.ACTION_DISABLE_VERSION,
            reason=reason,
        )
        # 下线的若是当前版本，回退到上一个可用 published 版本（无则 None）
        skill = Skill.objects.select_for_update().get(pk=v.skill_id)
        if skill.latest_version_id == v.id:
            fallback = (
                skill.versions
                .filter(status=SkillVersion.STATUS_PUBLISHED, is_available=True)
                .exclude(pk=v.id)
                .order_by("-version_no")
                .first()
            )
            skill.latest_version = fallback
            skill.save(update_fields=["latest_version"])


def enable_version(version: SkillVersion, *, actor, reason: str) -> None:
    """admin 上线单个版本：is_available False→True，写 ReviewAction(enable_version)。

    Raises:
        ValueError: reason 为空。
        InvalidOperationError: 已 available。
    """
    reason = _require_reason(reason, op="enable_version")

    with transaction.atomic():
        v = SkillVersion.objects.select_for_update().get(pk=version.pk)
        if v.is_available is True:
            raise InvalidOperationError(
                f"version {v.pk} 已上线。"
            )
        v.is_available = True
        v.save(update_fields=["is_available"])
        ReviewAction.objects.create(
            version=v,
            actor=actor,
            action=ReviewAction.ACTION_ENABLE_VERSION,
            reason=reason,
        )
