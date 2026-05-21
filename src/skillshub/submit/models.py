"""Skill 提交数据模型。

T5 实现 Skill + SkillVersion 两张表，状态机 7 状态，供后续 T6/T7/T8/T9/T10 使用。
"""
from django.conf import settings
from django.db import models


class Skill(models.Model):
    TYPE_CHOICES = [("skill", "Skill")]

    name = models.SlugField(max_length=50, unique=True, verbose_name="名称")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="skill", verbose_name="类型")
    description = models.CharField(max_length=200, verbose_name="简介")
    tags = models.JSONField(default=list, verbose_name="标签")
    # T6: FK 化。Django 自动暴露 skill.latest_version (related obj) +
    # skill.latest_version_id (int 列访问，与 T5 测试兼容)
    latest_version = models.ForeignKey(
        "SkillVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="最新版本",
    )
    # install_count: T10 增加；T5 初始化为 0
    install_count = models.PositiveIntegerField(default=0, verbose_name="安装次数")
    is_listed = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="上下线状态",
        help_text="是否在 catalog 公开侧露出。False=已下线（仅 owner/staff 详情可见，install 链接 404）。",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_skills",
        verbose_name="创建人",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="创建时间")

    class Meta:
        db_table = "submit_skills"
        verbose_name = "Skill"
        verbose_name_plural = "Skill 列表"

    def __str__(self) -> str:
        return self.name


class SkillVersion(models.Model):
    STATUS_PENDING_MACHINE = "pending_machine"
    STATUS_PENDING_REVIEW = "pending_review"
    STATUS_CHANGES_REQUESTED = "changes_requested"
    STATUS_PUBLISHED = "published"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING_MACHINE, "待机审"),
        (STATUS_PENDING_REVIEW, "待管理员审核"),
        (STATUS_CHANGES_REQUESTED, "需修改"),
        (STATUS_PUBLISHED, "已发布"),
        (STATUS_REJECTED, "已拒绝"),
        (STATUS_CANCELLED, "已取消"),
    ]

    TERMINAL_STATUSES = {STATUS_PUBLISHED, STATUS_REJECTED, STATUS_CANCELLED}
    NON_TERMINAL_STATUSES = {STATUS_PENDING_MACHINE, STATUS_PENDING_REVIEW, STATUS_CHANGES_REQUESTED}

    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="versions")
    version_no = models.PositiveIntegerField()
    file_path = models.CharField(max_length=500)
    sha256 = models.CharField(max_length=64)
    readme = models.TextField()
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING_MACHINE,
        db_index=True,
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_versions",
    )
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    machine_review_result = models.JSONField(null=True, blank=True)
    violations = models.JSONField(null=True, blank=True)
    llm_review_result = models.JSONField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_available = models.BooleanField(
        default=True,
        db_index=True,
        help_text="是否对用户可见可装。False=已下线版本（catalog ?v= 与 install 链接 404）。"
                  "与 skill 级 is_listed 正交：双闸门任一关都不可见。",
    )
    download_token = models.CharField(
        max_length=32, unique=True, null=True, blank=True,
        help_text="publish 时生成；URL 防爆破用，企业内不绑 user 不限次",
    )

    class Meta:
        db_table = "submit_skill_versions"
        verbose_name = "Skill 版本（待审 / 已发布）"
        verbose_name_plural = "Skill 版本"
        unique_together = [("skill", "version_no")]
        indexes = [
            models.Index(
                fields=["skill", "status", "-submitted_at"],
                name="sv_skill_status_submitted_at",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.skill.name} v{self.version_no} ({self.status})"


class ReviewAction(models.Model):
    """审核操作审计表（T8 R-7）。

    记录管理后台的全部人为操作 + 系统自动动作，用于审计与作者反馈：
    - 审核动作（admin）：approve / reject / request_changes
    - 治理动作（skill 级，admin）：delist / relist / rollback
    - 治理动作（版本级，admin）：disable_version / enable_version
    - 系统动作：cancel_by_author / auto_cancel_by_resubmit

    设计：
    - on_delete=PROTECT 双向：审计不可被级联删（删 version / 删 user 都报错）
    - reason TextField blank=True：approve 允许空 reason，reject/request_changes
      由 service 层强制非空
    """

    ACTION_APPROVE = "approve"
    ACTION_REJECT = "reject"
    ACTION_REQUEST_CHANGES = "request_changes"
    ACTION_CANCEL_BY_AUTHOR = "cancel_by_author"
    ACTION_AUTO_CANCEL_BY_RESUBMIT = "auto_cancel_by_resubmit"
    ACTION_DELIST = "delist"
    ACTION_RELIST = "relist"
    ACTION_ROLLBACK = "rollback"
    ACTION_DISABLE_VERSION = "disable_version"
    ACTION_ENABLE_VERSION = "enable_version"

    ACTION_CHOICES = [
        (ACTION_APPROVE, "Approve"),
        (ACTION_REJECT, "Reject"),
        (ACTION_REQUEST_CHANGES, "Request changes"),
        (ACTION_CANCEL_BY_AUTHOR, "Cancel by author"),
        (ACTION_AUTO_CANCEL_BY_RESUBMIT, "Auto cancel (resubmit)"),
        (ACTION_DELIST, "Delist"),
        (ACTION_RELIST, "Relist"),
        (ACTION_ROLLBACK, "Rollback"),
        (ACTION_DISABLE_VERSION, "Disable version"),
        (ACTION_ENABLE_VERSION, "Enable version"),
    ]

    version = models.ForeignKey(
        SkillVersion,
        on_delete=models.PROTECT,
        related_name="review_actions",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="review_actions",
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "submit_review_actions"
        verbose_name = "审核日志"
        verbose_name_plural = "审核日志"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["version", "-created_at"], name="ra_version_created"),
        ]

    def __str__(self) -> str:
        return f"ReviewAction({self.action} on v{self.version_id} by {self.actor_id})"


class PendingSkillVersion(SkillVersion):
    """SkillVersion 的 proxy，仅暴露 status=pending_review 的版本到 admin。

    与 SkillVersionAdmin 共享底层表；通过 PendingSkillVersionAdmin.get_queryset
    限制返回集合，并复用 T8 的 review/file URL（不重复注册）。
    """

    class Meta:
        proxy = True
        verbose_name = "Skill 审核"
        verbose_name_plural = "Skill 审核"
