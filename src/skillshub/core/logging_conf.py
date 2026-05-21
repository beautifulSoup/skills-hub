"""Logging 配置：DEBUG=True 人可读 console；DEBUG=False JSON to stdout。

build_logging_dict() 返回 Django 标准 LOGGING dictConfig；
在 settings.py 中 import 并赋值给 LOGGING。

JSON 模式包含 request_id（从 logging context 取，需 RequestIdFilter）。
"""
import logging
import threading


_request_id_local = threading.local()


def set_request_id(request_id: str) -> None:
    _request_id_local.request_id = request_id


def get_request_id() -> str:
    return getattr(_request_id_local, "request_id", "-")


class RequestIdFilter(logging.Filter):
    """把 request_id 注入到 log record。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def build_logging_dict(*, debug: bool) -> dict:
    formatter_key = "console" if debug else "json"
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "skillshub.core.logging_conf.RequestIdFilter"},
        },
        "formatters": {
            "console": {
                "format": "%(asctime)s [%(levelname)s] %(name)s [rid=%(request_id)s] %(message)s",
            },
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
                "rename_fields": {"asctime": "timestamp", "levelname": "level", "name": "logger"},
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "filters": ["request_id"],
                "formatter": formatter_key,
            },
        },
        "root": {
            "handlers": ["stdout"],
            "level": "INFO",
        },
        "loggers": {
            "django": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
            "celery": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        },
    }
