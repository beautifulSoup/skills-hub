"""Celery app definition for skills-hub。"""
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "skillshub.core.settings")

app = Celery("skillshub")

# 从 Django settings 读 CELERY_* 配置
app.config_from_object("django.conf:settings", namespace="CELERY")

# 自动从所有 INSTALLED_APPS 的 tasks.py 加载 task
app.autodiscover_tasks()
