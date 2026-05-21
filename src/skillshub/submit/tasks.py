"""Celery tasks for submit app.

T7 机审实施完成后，本 module 仅作 Celery autodiscover 入口；
真 task 实现在 skillshub.submit.machine_review.task。
"""
from skillshub.submit.machine_review.task import machine_review  # noqa: F401
