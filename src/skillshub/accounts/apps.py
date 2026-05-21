from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "skillshub.accounts"
    verbose_name = "账号管理"

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(_sync_initial_admins, sender=self)


def _sync_initial_admins(sender, **kwargs):
    """post_migrate signal handler：同步 INITIAL_ADMIN_EMAILS 到 User。

    设 is_staff=True + is_superuser=True：admin 审核台（unfold）需要 model 权限，
    仅 is_staff 而无权限的用户进得去 /admin 但菜单全空、每页 403。审计的增删改由
    各 ModelAdmin 的 has_*_permission=False 兜底（即使 superuser 也禁）。
    """
    from django.conf import settings
    from django.contrib.auth.models import User

    emails = getattr(settings, "INITIAL_ADMIN_EMAILS", [])
    for raw_email in emails:
        email = raw_email.lower().strip()
        if not email:
            continue
        user, created = User.objects.get_or_create(
            username=email,
            defaults={"email": email, "is_active": True},
        )
        if created:
            user.set_unusable_password()
        user.is_staff = True
        user.is_superuser = True
        fields = ["password", "is_staff", "is_superuser"] if created else ["is_staff", "is_superuser"]
        user.save(update_fields=fields)
