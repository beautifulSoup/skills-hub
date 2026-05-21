"""Tests for accounts.throttle module."""
import pytest
from freezegun import freeze_time

from skillshub.accounts.models import OtpCode
from skillshub.accounts.throttle import is_throttled

pytestmark = pytest.mark.django_db


def test_no_records_not_throttled():
    throttled, remaining = is_throttled("user@x.com")
    assert throttled is False
    assert remaining == 0


def test_recent_record_throttled():
    with freeze_time("2026-01-01 10:00:00") as frozen:
        from django.utils import timezone
        from datetime import timedelta
        OtpCode.objects.create(
            email="user@x.com",
            code="123456",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        # 30 seconds later → still throttled
        frozen.tick(delta=timedelta(seconds=30))
        throttled, remaining = is_throttled("user@x.com")
    assert throttled is True
    assert remaining == 30  # 60 - 30 = 30


def test_old_record_not_throttled():
    with freeze_time("2026-01-01 10:00:00") as frozen:
        from django.utils import timezone
        from datetime import timedelta
        OtpCode.objects.create(
            email="user@x.com",
            code="123456",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        # 65 seconds later → past throttle window
        frozen.tick(delta=timedelta(seconds=65))
        throttled, remaining = is_throttled("user@x.com")
    assert throttled is False
    assert remaining == 0
