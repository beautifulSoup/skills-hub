"""T7 机审引擎。

包含 violations.py（Violation dataclass + code 常量）、l1.py（结构校验）、
l2.py（安全扫描）、task.py（Celery task）。Autodiscover 入口在父级
submit/tasks.py，从 machine_review.task re-export `machine_review` task。
"""
