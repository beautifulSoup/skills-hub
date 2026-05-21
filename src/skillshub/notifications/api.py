"""Notifications 公开 API（仅 2 个场景化函数 + 1 个 internal 通用函数）。

Caller (T2 / T8) 应该调 `send_otp_email` / `send_review_result_email`，
不要绕过场景化封装直接调 `_send_email`（按 D-T11-1，底层 internal 防止
模板路径四处散落难维护）。
"""
from skillshub.notifications.tasks import send_email_task

# 审核 decision 到模板 base 名的映射
_REVIEW_TEMPLATE_BASE = {
    "approve": "review_approve",
    "reject": "review_reject",
    "changes_requested": "review_changes_requested",
}


def _send_email(
    to: str,
    subject_template: str,
    body_text_template: str,
    body_html_template: str,
    context: dict,
) -> None:
    """Internal: 入队邮件发送 task（fire-and-forget）。

    上层场景化函数（send_otp_email / send_review_result_email）调用本函数。
    外部 caller **请勿**直接使用——用对应的场景化函数。
    """
    send_email_task.delay(
        to=[to],
        subject_template=subject_template,
        body_text_template=body_text_template,
        body_html_template=body_html_template,
        context=context,
    )


def send_otp_email(to: str, code: str, ttl_minutes: int = 5) -> None:
    """T2 调用：发 OTP 验证码邮件。Fire-and-forget。"""
    _send_email(
        to=to,
        subject_template="notifications/otp_subject.txt",
        body_text_template="notifications/otp_body.txt",
        body_html_template="notifications/otp_body.html",
        context={"code": code, "ttl_minutes": ttl_minutes},
    )


def send_review_result_email(
    to: str,
    decision: str,
    skill_name: str,
    version_no: int,
    reason: str,
    review_url: str,
) -> None:
    """T8 调用：发审核结果邮件给作者。Fire-and-forget。

    Args:
        decision: 必须为 "approve" / "reject" / "changes_requested" 之一，否则 ValueError
        reason: approve 可空字符串；reject 与 changes_requested 必填
    """
    if decision not in _REVIEW_TEMPLATE_BASE:
        raise ValueError(
            f"Invalid decision={decision!r}; must be one of {list(_REVIEW_TEMPLATE_BASE)}"
        )
    base = _REVIEW_TEMPLATE_BASE[decision]
    _send_email(
        to=to,
        subject_template=f"notifications/{base}_subject.txt",
        body_text_template=f"notifications/{base}_body.txt",
        body_html_template=f"notifications/{base}_body.html",
        context={
            "skill_name": skill_name,
            "version_no": version_no,
            "reason": reason,
            "review_url": review_url,
        },
    )
