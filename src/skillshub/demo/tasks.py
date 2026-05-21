"""Demo Celery tasks（用于 T1 全链路烟雾测试，T1 完成后保留）。"""
import time
from celery import shared_task


@shared_task
def add(x: int, y: int) -> int:
    """模拟有耗时的加法任务。"""
    time.sleep(1)
    return x + y
