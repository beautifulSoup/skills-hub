"""T11 Celery task 测试：失败入死信表。

按 Celery 官方测试指南（docs/userguide/testing.rst）：
    "EAGER mode is NOT suitable for unit tests because it only emulates worker behavior."

所以本文件不通过 .apply() 测 retry 流程；而是 **直接 unit-test on_failure hook 函数**
（验证持久化逻辑），retry 流程的 integration test 留给生产 worker 集成。
"""
from smtplib import SMTPException
from unittest.mock import MagicMock

import pytest

from skillshub.notifications.models import FailedEmail
from skillshub.notifications.tasks import EmailTask

pytestmark = pytest.mark.django_db


def _make_email_task_with_retries(retries: int) -> EmailTask:
    """构造一个 EmailTask 实例，request.retries 设为指定值（attempts 计算用）。"""
    task = EmailTask()
    task.request_stack = MagicMock()
    task.request_stack.top = MagicMock(retries=retries)
    return task


def test_on_failure_creates_failed_email_for_smtp_exception():
    """SMTP 异常 → on_failure → FailedEmail 入库（含 attempts = retries+1）。"""
    assert FailedEmail.objects.count() == 0

    task = _make_email_task_with_retries(retries=3)   # 模拟 retry 用尽（max_retries=3）
    exc = SMTPException("simulated SMTP failure")

    task.on_failure(
        exc=exc,
        task_id="test-task-id-001",
        args=(),
        kwargs={
            "to": ["user@example.com"],
            "subject_template": "notifications/otp_subject.txt",
            "body_text_template": "notifications/otp_body.txt",
            "body_html_template": "notifications/otp_body.html",
            "context": {"code": "999999", "ttl_minutes": 5},
        },
        einfo=None,
    )

    assert FailedEmail.objects.count() == 1
    fe = FailedEmail.objects.first()
    assert fe.to == ["user@example.com"]
    assert fe.subject_template == "notifications/otp_subject.txt"
    assert fe.context == {"code": "999999", "ttl_minutes": 5}
    assert "SMTP" in fe.last_error or "simulated" in fe.last_error
    assert fe.attempts == 4   # retries(3) + 1


def test_on_failure_creates_failed_email_for_template_error():
    """非 retry 异常（如 TemplateDoesNotExist）→ on_failure → FailedEmail 入库（attempts=1）。"""
    from django.template.exceptions import TemplateDoesNotExist

    assert FailedEmail.objects.count() == 0

    task = _make_email_task_with_retries(retries=0)   # 模板错首次失败即调 on_failure，没 retry
    exc = TemplateDoesNotExist("notifications/nonexistent.txt")

    task.on_failure(
        exc=exc,
        task_id="test-task-id-002",
        args=(),
        kwargs={
            "to": ["x@y.com"],
            "subject_template": "notifications/nonexistent.txt",
            "body_text_template": "notifications/otp_body.txt",
            "body_html_template": "notifications/otp_body.html",
            "context": {"code": "1"},
        },
        einfo=None,
    )

    assert FailedEmail.objects.count() == 1
    fe = FailedEmail.objects.first()
    assert "nonexistent" in fe.last_error or "TemplateDoesNotExist" in fe.last_error
    assert fe.attempts == 1
