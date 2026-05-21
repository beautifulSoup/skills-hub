"""失败邮件持久化（死信表，admin 可见）。"""
from django.db import models


class FailedEmail(models.Model):
    """超过 Celery 重试次数后入这张表，admin 可见用于 oncall。"""

    # 邮件原始入参（足以重发；若未来加 admin retry action 时用）
    to = models.JSONField(help_text="收件人列表，如 ['user@example.com']")
    subject_template = models.CharField(max_length=200)
    body_text_template = models.CharField(max_length=200)
    body_html_template = models.CharField(max_length=200)
    context = models.JSONField(help_text="渲染模板用的 context dict")

    # 失败信息
    last_error = models.TextField(help_text="最后一次失败的 exception traceback")
    attempts = models.PositiveIntegerField(help_text="累计尝试次数（含 Celery 重试）")

    # 元数据
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(
        null=True, blank=True, help_text="手动重发成功后置 now()（v0.1 暂不实现自动重发，预留字段）"
    )

    class Meta:
        db_table = "notifications_failed_emails"
        verbose_name = "失败邮件"
        verbose_name_plural = "失败邮件队列"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["resolved_at", "-created_at"])]

    def __str__(self) -> str:
        return f"FailedEmail(to={self.to}, subject={self.subject_template}, attempts={self.attempts})"
