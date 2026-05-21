"""T2 业务逻辑层。View 只做协调，所有规则在这里。"""
import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from skillshub.accounts.models import OtpCode
from skillshub.notifications.api import send_otp_email

OTP_TTL_MINUTES = 5
MAX_ATTEMPTS = 5


def generate_otp(email: str) -> OtpCode:
    """生成 6 位 OTP，插 OtpCode 行，发邮件。返回 OtpCode 实例。"""
    email = email.lower().strip()
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    expires_at = timezone.now() + timedelta(minutes=OTP_TTL_MINUTES)
    otp = OtpCode.objects.create(email=email, code=code, expires_at=expires_at)
    send_otp_email(to=email, code=code, ttl_minutes=OTP_TTL_MINUTES)
    return otp


def verify_otp_code(email: str, submitted_code: str) -> tuple[bool, str]:
    """验证 OTP。返回 (success, error_msg)。error_msg 空字符串表示成功。"""
    email = email.lower().strip()
    otp = (
        OtpCode.objects.filter(email=email, is_used=False)
        .order_by("-created_at")
        .first()
    )
    if otp is None:
        return False, "验证码不存在，请重新发送"

    if otp.is_expired():
        otp.is_used = True
        otp.save(update_fields=["is_used"])
        return False, "已过期，请重新发送"

    if otp.attempts >= MAX_ATTEMPTS:
        otp.is_used = True
        otp.save(update_fields=["is_used"])
        return False, "验证码已失效，请重新发送"

    if otp.code != submitted_code:
        otp.attempts += 1
        if otp.attempts >= MAX_ATTEMPTS:
            otp.is_used = True
            otp.save(update_fields=["attempts", "is_used"])
            return False, "验证码已失效，请重新发送"
        otp.save(update_fields=["attempts"])
        remaining = MAX_ATTEMPTS - otp.attempts
        return False, f"验证码错误，还剩 {remaining} 次机会"

    # 验证成功
    otp.is_used = True
    otp.save(update_fields=["is_used"])
    return True, ""


def login_or_create_user(email: str) -> User:
    """OTP 通过后 get-or-create user，确保 unusable password。"""
    email = email.lower().strip()
    user, created = User.objects.get_or_create(
        username=email,
        defaults={"email": email, "is_active": True},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user
