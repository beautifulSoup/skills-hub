"""Tests for LocalStorage (task 7.1)."""
import pytest
from django.test import override_settings


def make_local(tmp_path):
    """Create a LocalStorage instance pointing at tmp_path."""
    from skillshub.storage.local_backend import LocalStorage
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        storage = LocalStorage()
    return storage


@pytest.fixture()
def local(tmp_path):
    return make_local(tmp_path)


@pytest.mark.django_db
def test_save_and_get_roundtrip(tmp_path):
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        from skillshub.storage.local_backend import LocalStorage
        storage = LocalStorage()
        storage.save("a/b.txt", b"hello")
        assert storage.get("a/b.txt") == b"hello"
        assert (tmp_path / "a" / "b.txt").exists()


@pytest.mark.django_db
def test_save_creates_subdirs(tmp_path):
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        from skillshub.storage.local_backend import LocalStorage
        storage = LocalStorage()
        storage.save("nested/deep/path/file.txt", b"x")
        assert (tmp_path / "nested" / "deep" / "path" / "file.txt").read_bytes() == b"x"


@pytest.mark.django_db
def test_get_nonexistent_raises_FileNotFoundError(tmp_path):
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        from skillshub.storage.local_backend import LocalStorage
        storage = LocalStorage()
        with pytest.raises(FileNotFoundError):
            storage.get("nonexistent.txt")


@pytest.mark.django_db
def test_url_returns_media_path(tmp_path):
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        from skillshub.storage.local_backend import LocalStorage
        storage = LocalStorage()
        assert storage.url("skills/foo.zip") == "/media/skills/foo.zip"


@pytest.mark.django_db
def test_delete_idempotent(tmp_path):
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        from skillshub.storage.local_backend import LocalStorage
        storage = LocalStorage()
        storage.save("to_delete.txt", b"bye")
        storage.delete("to_delete.txt")
        # File is gone
        with pytest.raises(FileNotFoundError):
            storage.get("to_delete.txt")
        # Calling delete again should not raise
        storage.delete("to_delete.txt")


@pytest.mark.django_db
def test_path_traversal_with_dotdot_blocked(tmp_path):
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        from skillshub.storage.local_backend import LocalStorage
        storage = LocalStorage()
        with pytest.raises(ValueError):
            storage.save("../../etc/passwd", b"x")


@pytest.mark.django_db
def test_path_traversal_with_absolute_path_blocked(tmp_path):
    with override_settings(STORAGE_LOCAL_ROOT=str(tmp_path), MEDIA_URL="/media/"):
        from skillshub.storage.local_backend import LocalStorage
        storage = LocalStorage()
        with pytest.raises(ValueError):
            storage.save("/etc/passwd", b"x")
