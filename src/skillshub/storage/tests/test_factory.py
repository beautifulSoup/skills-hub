"""Tests for get_storage() factory (task 7.3)."""
import pytest
from unittest.mock import patch, MagicMock
from django.test import override_settings


OSS_SETTINGS = dict(
    STORAGE_OSS_ACCESS_KEY_ID="k",
    STORAGE_OSS_ACCESS_KEY_SECRET="s",
    STORAGE_OSS_ENDPOINT="https://oss-endpoint",
    STORAGE_OSS_BUCKET="bucket",
)


@pytest.fixture(autouse=True)
def reset_storage_cache():
    """Ensure the module-level cache is cleared before and after each test."""
    from skillshub.storage import api
    api.reset_storage()
    yield
    api.reset_storage()


@pytest.mark.django_db
def test_get_storage_local_returns_LocalStorage(tmp_path):
    from skillshub.storage.local_backend import LocalStorage
    from skillshub.storage.api import get_storage
    with override_settings(STORAGE_BACKEND="local", STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        result = get_storage()
    assert isinstance(result, LocalStorage)


@pytest.mark.django_db
def test_get_storage_aliyun_returns_AliyunOssStorage():
    with patch("skillshub.storage.aliyun_backend.oss2") as mock_oss2:
        mock_oss2.Auth.return_value = MagicMock()
        mock_oss2.Bucket.return_value = MagicMock()
        from skillshub.storage.aliyun_backend import AliyunOssStorage
        from skillshub.storage.api import get_storage
        with override_settings(STORAGE_BACKEND="aliyun_oss", **OSS_SETTINGS):
            result = get_storage()
        assert isinstance(result, AliyunOssStorage)


@pytest.mark.django_db
def test_get_storage_invalid_raises_ValueError():
    from skillshub.storage.api import get_storage
    with override_settings(STORAGE_BACKEND="unknown"):
        with pytest.raises(ValueError, match="unknown"):
            get_storage()


@pytest.mark.django_db
def test_get_storage_caches_instance(tmp_path):
    from skillshub.storage.api import get_storage
    with override_settings(STORAGE_BACKEND="local", STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        first = get_storage()
        second = get_storage()
    assert first is second


@pytest.mark.django_db
def test_reset_storage_clears_cache(tmp_path):
    from skillshub.storage.api import get_storage, reset_storage
    with override_settings(STORAGE_BACKEND="local", STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        first = get_storage()
        reset_storage()
        second = get_storage()
    assert first is not second
