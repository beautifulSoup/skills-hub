"""Tests for accounts.services module."""
import pytest
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from freezegun import freeze_time

from skillshub.accounts.models import OtpCode
from skillshub.accounts.services import generate_otp, login_or_create_user, verify_otp_code

pytestmark = pytest.mark.django_db


@patch("skillshub.accounts.services.send_otp_email")
def test_generate_otp_creates_row(mock_send):
    otp = generate_otp("Alice@Example.com")
    assert otp.pk is not None
    assert len(otp.code) == 6
    assert otp.code.isdigit()
    assert otp.is_used is False
    assert otp.attempts == 0
    # email should be lowercased
    assert otp.email == "alice@example.com"
    mock_send.assert_called_once()


@patch("skillshub.accounts.services.send_otp_email")
def test_verify_otp_success(mock_send):
    otp = generate_otp("user@x.com")
    success, msg = verify_otp_code("user@x.com", otp.code)
    assert success is True
    assert msg == ""
    otp.refresh_from_db()
    assert otp.is_used is True


@patch("skillshub.accounts.services.send_otp_email")
def test_verify_otp_wrong_code_increments_attempts(mock_send):
    otp = generate_otp("user@x.com")
    success, msg = verify_otp_code("user@x.com", "000000")
    assert success is False
    assert "错误" in msg
    otp.refresh_from_db()
    assert otp.attempts == 1


@patch("skillshub.accounts.services.send_otp_email")
def test_verify_otp_five_failures_invalidates(mock_send):
    otp = generate_otp("user@x.com")
    # 4 wrong attempts
    for _ in range(4):
        verify_otp_code("user@x.com", "000000")
    # 5th wrong attempt → is_used=True
    success, msg = verify_otp_code("user@x.com", "000000")
    assert success is False
    assert "失效" in msg
    otp.refresh_from_db()
    assert otp.is_used is True
    assert otp.attempts == 5


@patch("skillshub.accounts.services.send_otp_email")
def test_verify_otp_expired(mock_send):
    with freeze_time("2026-01-01 10:00:00"):
        otp = generate_otp("user@x.com")
    # Jump 6 minutes into the future (past 5-min TTL)
    with freeze_time("2026-01-01 10:06:00"):
        success, msg = verify_otp_code("user@x.com", otp.code)
    assert success is False
    assert "过期" in msg
    otp.refresh_from_db()
    assert otp.is_used is True


@patch("skillshub.accounts.services.send_otp_email")
def test_login_or_create_user_creates_new(mock_send):
    user = login_or_create_user("newuser@x.com")
    assert user.username == "newuser@x.com"
    assert user.email == "newuser@x.com"
    assert user.is_active is True
    assert not user.has_usable_password()


@patch("skillshub.accounts.services.send_otp_email")
def test_login_or_create_user_returns_existing(mock_send):
    from django.contrib.auth.models import User
    existing = User.objects.create_user(username="existing@x.com", email="existing@x.com")
    user = login_or_create_user("existing@x.com")
    assert user.pk == existing.pk
