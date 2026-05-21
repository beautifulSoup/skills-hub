"""LocalStorage — pathlib-based local filesystem backend (D-T3-3, D-T3-6)."""
from pathlib import Path

from django.conf import settings


class LocalStorage:
    """Stores files under STORAGE_LOCAL_ROOT with strict path traversal defence."""

    def __init__(self) -> None:
        self._root = Path(settings.STORAGE_LOCAL_ROOT).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _full(self, path: str) -> Path:
        """Resolve path and verify it stays inside _root; raise ValueError if not."""
        # Prevent absolute paths from bypassing root — join with root first
        resolved = (self._root / path).resolve()
        if not str(resolved).startswith(str(self._root) + "/") and resolved != self._root:
            raise ValueError(
                f"Path '{path}' resolves outside STORAGE_LOCAL_ROOT '{self._root}'"
            )
        return resolved

    def save(self, path: str, content: bytes) -> str:
        full = self._full(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content)
        return path

    def get(self, path: str) -> bytes:
        full = self._full(path)
        if not full.exists():
            raise FileNotFoundError(f"File not found in storage: '{path}'")
        return full.read_bytes()

    def url(self, path: str) -> str:
        media_url = settings.MEDIA_URL
        # Ensure no double slash: MEDIA_URL ends with '/', path must not start with '/'
        return f"{media_url.rstrip('/')}/{path.lstrip('/')}"

    def delete(self, path: str) -> None:
        full = self._full(path)
        if full.exists():
            full.unlink()
