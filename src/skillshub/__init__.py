"""skills-hub package：导出 Celery app 让 worker 找得到。"""
from skillshub.core.celery import app as celery_app

__all__ = ("celery_app",)
