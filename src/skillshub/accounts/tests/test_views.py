"""End-to-end view tests using Django test Client + mail.outbox."""
import re
import pytest
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client

pytestmark = pytest.mark.django_db


EMAIL = "testuser@example.com"
WHITELIST = ["example.com"]


def test_login_page_get(client):
    resp = client.get("/login/")
    assert resp.status_code == 200
    assert "邮箱" in resp.content.decode()


@patch("skillshub.accounts.views.is_email_allowed", return_value=True)
@patch("skillshub.accounts.views.throttle_mod.is_throttled", return_value=(False, 0))
def test_full_login_flow(mock_throttle, mock_whitelist, client):
    # Step 1: POST request-otp
    resp = client.post("/login/request-otp", {"email": EMAIL})
    assert resp.status_code == 200
    assert "验证码已发送" in resp.content.decode()

    # Step 2: Extract OTP from mail.outbox
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    # The OTP template should include the 6-digit code
    # Look for 6-digit sequence in email body
    match = re.search(r"\b(\d{6})\b", body)
    assert match, f"No 6-digit OTP found in email body: {body!r}"
    code = match.group(1)

    # Step 3: POST verify
    resp = client.post("/login/verify", {"email": EMAIL, "code": code})
    assert resp.status_code == 200
    assert resp.get("HX-Redirect") == "/"

    # Verify session is set (user is authenticated)
    resp2 = client.get("/")
    assert resp2.status_code == 200


@patch("skillshub.accounts.views.is_email_allowed", return_value=False)
def test_request_otp_whitelist_rejected(mock_whitelist, client):
    resp = client.post("/login/request-otp", {"email": "hacker@gmail.com"})
    assert resp.status_code == 200
    assert "不在允许范围" in resp.content.decode()
    assert len(mail.outbox) == 0


@patch("skillshub.accounts.views.is_email_allowed", return_value=True)
@patch("skillshub.accounts.views.throttle_mod.is_throttled", return_value=(True, 42))
def test_request_otp_throttled(mock_throttle, mock_whitelist, client):
    resp = client.post("/login/request-otp", {"email": EMAIL})
    assert resp.status_code == 200
    assert "42" in resp.content.decode()
    assert len(mail.outbox) == 0
