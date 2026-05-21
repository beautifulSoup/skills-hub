"""Notifications Celery tasks。

`send_email_task` 是 T11 唯一的 Celery task：
- 渲染 multipart 邮件（HTML + 纯文本 fallback）
- 通过 Django EMAIL_BACKEND 发送
- SMTP 临时故障自动重试（指数退避，max 3 次）— Celery autoretry_for 处理
- 重试用尽 / 非 retry 异常 → Task class 的 on_failure hook 持久化到 FailedEmail 表

设计选择：用 Task base class + on_failure（Celery 官方推荐 hook，
EAGER / 真 broker 模式都触发），不用 task_failure signal（sender 匹配 quirky）。
"""
import logging
import traceback
from smtplib import SMTPException

from celery import Task, shared_task
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


class EmailTask(Task):
    """Base task for email sending; on_failure 持久化死信。"""

    autoretry_for = (SMTPException, OSError)
    max_retries = 3
    retry_backoff = True              # 60s → 120s → 240s
    retry_backoff_max = 600

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Celery 在重试用尽 / 非 retry 异常后调用此 hook。"""
        from skillshub.notifications.models import FailedEmail   # 局部 import 防 app loading 循环

        error_text = ""
        if einfo is not None:
            error_text = str(einfo)
        elif exc is not None:
            error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        args = args or ()
        kwargs = kwargs or {}
        try:
            FailedEmail.objects.create(
                to=kwargs.get("to") or (args[0] if len(args) > 0 else []),
                subject_template=kwargs.get("subject_template") or (args[1] if len(args) > 1 else ""),
                body_text_template=kwargs.get("body_text_template") or (args[2] if len(args) > 2 else ""),
                body_html_template=kwargs.get("body_html_template") or (args[3] if len(args) > 3 else ""),
                context=kwargs.get("context") or (args[4] if len(args) > 4 else {}),
                last_error=error_text,
                attempts=self.request.retries + 1,
            )
        except Exception:
            logger.exception("Failed to persist FailedEmail record (task_id=%s)", task_id)


@shared_task(bind=True, base=EmailTask)
def send_email_task(
    self,
    to: list,
    subject_template: str,
    body_text_template: str,
    body_html_template: str,
    context: dict,
) -> None:
    """异步发送一封 multipart 邮件。

    依赖 EmailTask base class：
    - autoretry_for=(SMTPException, OSError) → 网络/SMTP 错自动 retry
    - max_retries=3 + retry_backoff → 60s → 120s → 240s
    - on_failure → retry 用尽 / 模板渲染错等非 retry 异常 → 入 FailedEmail
    """
    subject = render_to_string(subject_template, context).strip()
    body_text = render_to_string(body_text_template, context)
    body_html = render_to_string(body_html_template, context)

    msg = EmailMultiAlternatives(subject=subject, body=body_text, to=to)
    msg.attach_alternative(body_html, "text/html")
    msg.send(fail_silently=False)
