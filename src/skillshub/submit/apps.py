"""Submit app configuration."""
from django.apps import AppConfig


class SubmitConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "skillshub.submit"
    verbose_name = "Skill 审核"
