from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "skillshub.notifications"
    verbose_name = "邮件通知"
