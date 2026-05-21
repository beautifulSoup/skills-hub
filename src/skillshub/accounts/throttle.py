import math
from datetime import timedelta

from django.utils import timezone

from skillshub.accounts.models import OtpCode

THROTTLE_SECONDS = 60


def is_throttled(email: str) -> tuple[bool, int]:
    """Return (throttled, remaining_seconds).

    Checks whether the email has requested an OTP within the last THROTTLE_SECONDS.
    """
    email = email.lower().strip()
    cutoff = timezone.now() - timedelta(seconds=THROTTLE_SECONDS)
    latest = (
        OtpCode.objects.filter(email=email, created_at__gte=cutoff)
        .order_by("-created_at")
        .first()
    )
    if latest is None:
        return False, 0
    elapsed = (timezone.now() - latest.created_at).total_seconds()
    remaining = THROTTLE_SECONDS - elapsed
    if remaining > 0:
        return True, math.ceil(remaining)
    return False, 0
