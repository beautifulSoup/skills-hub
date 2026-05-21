"""pytest-django 全局 fixtures。"""
import pytest


@pytest.fixture(autouse=True)
def celery_eager(settings):
    """所有测试默认让 Celery task 同步执行，不依赖 worker 容器。

    本地运行（TEST_USE_SQLITE=1）时，settings.py 已在启动时将 Celery
    切换为内存 broker/backend；此 fixture 仅做二次确认。
    容器内运行时（无 TEST_USE_SQLITE）需在此显式覆写。
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    settings.CELERY_TASK_STORE_EAGER_RESULT = True
