from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class AdminUser(User):
    """auth.User 的 proxy —— 在 admin 中以「管理员」名义展示。

    模型/表无变化，仅覆盖 verbose_name + 走独立 admin 注册。
    """

    class Meta:
        proxy = True
        verbose_name = "管理员"
        verbose_name_plural = "管理员"


class OtpCode(models.Model):
    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "accounts_otp_codes"
        indexes = [
            models.Index(fields=["email", "is_used", "-created_at"], name="otp_email_used_created_idx"),
        ]

    def is_expired(self):
        return timezone.now() > self.expires_at
