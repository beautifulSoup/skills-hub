"""AliyunOssStorage — oss2-based Aliyun OSS backend (D-T3-4, D-T3-5)."""
import oss2

from django.conf import settings


class AliyunOssStorage:
    """Stores files on Aliyun OSS; url() returns signed URL with 1-hour TTL."""

    def __init__(self) -> None:
        auth = oss2.Auth(
            settings.STORAGE_OSS_ACCESS_KEY_ID,
            settings.STORAGE_OSS_ACCESS_KEY_SECRET,
        )
        self._bucket = oss2.Bucket(
            auth,
            settings.STORAGE_OSS_ENDPOINT,
            settings.STORAGE_OSS_BUCKET,
        )

    def save(self, path: str, content: bytes) -> str:
        self._bucket.put_object(path, content)
        return path

    def get(self, path: str) -> bytes:
        try:
            return self._bucket.get_object(path).read()
        except oss2.exceptions.NoSuchKey:
            raise FileNotFoundError(f"File not found in OSS: '{path}'")

    def url(self, path: str) -> str:
        return self._bucket.sign_url("GET", path, 3600)

    def delete(self, path: str) -> None:
        # OSS delete_object is idempotent by default (no error if key absent)
        self._bucket.delete_object(path)
