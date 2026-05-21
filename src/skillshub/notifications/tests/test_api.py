"""T11 公开 API 测试（用 locmem backend；EAGER mode 下 send_email_task 同步执行）。"""
import pytest
from django.core import mail

from skillshub.notifications.api import send_otp_email, send_review_result_email

pytestmark = pytest.mark.django_db


def test_send_otp_email_puts_one_message_in_outbox():
    mail.outbox.clear()
    send_otp_email(to="user@example.com", code="123456", ttl_minutes=5)
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["user@example.com"]
    assert "123456" in msg.subject
    assert "123456" in msg.body
    assert "5" in msg.body  # ttl_minutes
    # 验证 multipart：alternatives 含 HTML
    assert any("text/html" in alt[1] for alt in msg.alternatives)
    assert any("123456" in alt[0] for alt in msg.alternatives)


@pytest.mark.parametrize(
    "decision,expected_subject_keyword",
    [
        ("approve", "通过审核"),
        ("reject", "未通过"),
        ("changes_requested", "需要修改"),
    ],
)
def test_send_review_result_email_each_decision(decision, expected_subject_keyword):
    mail.outbox.clear()
    send_review_result_email(
        to="author@example.com",
        decision=decision,
        skill_name="my-skill",
        version_no=2,
        reason="some reason text",
        review_url="https://hub.example.com/skills/my-skill/v2",
    )
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["author@example.com"]
    assert "my-skill" in msg.subject
    assert "v2" in msg.subject
    assert expected_subject_keyword in msg.subject
    # body 含必要字段
    assert "my-skill" in msg.body
    assert "https://hub.example.com/skills/my-skill/v2" in msg.body
    if decision != "approve":
        assert "some reason text" in msg.body


def test_send_review_result_email_invalid_decision_raises():
    with pytest.raises(ValueError, match="Invalid decision"):
        send_review_result_email(
            to="x@y.com",
            decision="invalid",
            skill_name="x",
            version_no=1,
            reason="",
            review_url="https://x",
        )
