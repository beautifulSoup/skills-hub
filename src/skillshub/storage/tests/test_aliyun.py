"""Tests for AliyunOssStorage (task 7.2) — fully mocked, no real OSS calls."""
import pytest
from unittest.mock import patch, MagicMock
from django.test import override_settings


OSS_SETTINGS = dict(
    STORAGE_OSS_ACCESS_KEY_ID="test-key-id",
    STORAGE_OSS_ACCESS_KEY_SECRET="test-key-secret",
    STORAGE_OSS_ENDPOINT="https://oss-cn-hangzhou.aliyuncs.com",
    STORAGE_OSS_BUCKET="test-bucket",
)


def make_aliyun(mock_oss2):
    """Build an AliyunOssStorage with a mocked oss2 module."""
    with override_settings(**OSS_SETTINGS):
        from skillshub.storage.aliyun_backend import AliyunOssStorage
        storage = AliyunOssStorage()
    return storage


@pytest.mark.django_db
def test_save_calls_put_object():
    with patch("skillshub.storage.aliyun_backend.oss2") as mock_oss2:
        mock_bucket = MagicMock()
        mock_oss2.Auth.return_value = MagicMock()
        mock_oss2.Bucket.return_value = mock_bucket
        with override_settings(**OSS_SETTINGS):
            from skillshub.storage.aliyun_backend import AliyunOssStorage
            storage = AliyunOssStorage()
            storage.save("foo.zip", b"data")
        mock_bucket.put_object.assert_called_once_with("foo.zip", b"data")


@pytest.mark.django_db
def test_get_returns_bytes():
    with patch("skillshub.storage.aliyun_backend.oss2") as mock_oss2:
        mock_bucket = MagicMock()
        mock_response = MagicMock()
        mock_response.read.return_value = b"content"
        mock_bucket.get_object.return_value = mock_response
        mock_oss2.Auth.return_value = MagicMock()
        mock_oss2.Bucket.return_value = mock_bucket
        with override_settings(**OSS_SETTINGS):
            from skillshub.storage.aliyun_backend import AliyunOssStorage
            storage = AliyunOssStorage()
            result = storage.get("foo.zip")
        assert result == b"content"
        mock_bucket.get_object.assert_called_once_with("foo.zip")


@pytest.mark.django_db
def test_get_nosuchkey_raises_FileNotFoundError():
    with patch("skillshub.storage.aliyun_backend.oss2") as mock_oss2:
        mock_bucket = MagicMock()
        # Simulate NoSuchKey exception
        no_such_key = type("NoSuchKey", (Exception,), {})
        mock_oss2.exceptions.NoSuchKey = no_such_key
        mock_bucket.get_object.side_effect = no_such_key()
        mock_oss2.Auth.return_value = MagicMock()
        mock_oss2.Bucket.return_value = mock_bucket
        with override_settings(**OSS_SETTINGS):
            from skillshub.storage.aliyun_backend import AliyunOssStorage
            storage = AliyunOssStorage()
            with pytest.raises(FileNotFoundError):
                storage.get("missing.txt")


@pytest.mark.django_db
def test_url_calls_sign_url_with_3600():
    with patch("skillshub.storage.aliyun_backend.oss2") as mock_oss2:
        mock_bucket = MagicMock()
        mock_bucket.sign_url.return_value = "https://signed-url"
        mock_oss2.Auth.return_value = MagicMock()
        mock_oss2.Bucket.return_value = mock_bucket
        with override_settings(**OSS_SETTINGS):
            from skillshub.storage.aliyun_backend import AliyunOssStorage
            storage = AliyunOssStorage()
            result = storage.url("foo.zip")
        mock_bucket.sign_url.assert_called_once_with("GET", "foo.zip", 3600)
        assert result == "https://signed-url"


@pytest.mark.django_db
def test_delete_calls_delete_object():
    with patch("skillshub.storage.aliyun_backend.oss2") as mock_oss2:
        mock_bucket = MagicMock()
        mock_oss2.Auth.return_value = MagicMock()
        mock_oss2.Bucket.return_value = mock_bucket
        with override_settings(**OSS_SETTINGS):
            from skillshub.storage.aliyun_backend import AliyunOssStorage
            storage = AliyunOssStorage()
            storage.delete("foo.zip")
        mock_bucket.delete_object.assert_called_once_with("foo.zip")
