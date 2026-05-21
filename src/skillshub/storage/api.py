"""Storage factory — lazy instantiation + module-level cache (D-T3-5)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from skillshub.storage.interface import Storage

_STORAGE_INSTANCE: "Storage | None" = None


def get_storage() -> "Storage":
    """Return cached storage backend; instantiate on first call."""
    global _STORAGE_INSTANCE
    if _STORAGE_INSTANCE is None:
        _STORAGE_INSTANCE = _create_storage()
    return _STORAGE_INSTANCE


def reset_storage() -> None:
    """Clear cached instance. Use in tests or after env change + restart."""
    global _STORAGE_INSTANCE
    _STORAGE_INSTANCE = None


def _create_storage() -> "Storage":
    backend = settings.STORAGE_BACKEND
    if backend == "local":
        from skillshub.storage.local_backend import LocalStorage
        return LocalStorage()
    elif backend == "aliyun_oss":
        from skillshub.storage.aliyun_backend import AliyunOssStorage
        return AliyunOssStorage()
    else:
        raise ValueError(
            f"Unknown STORAGE_BACKEND '{backend}'. "
            "Supported values: 'local', 'aliyun_oss'."
        )
