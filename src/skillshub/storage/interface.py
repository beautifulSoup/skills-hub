"""Storage Protocol — PEP 544 structural typing (D-T3-1)."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Storage(Protocol):
    """4-method interface for file storage backends.

    Backends do NOT need to inherit from this class (duck typing).
    Any class with matching method signatures satisfies the protocol.
    """

    def save(self, path: str, content: bytes) -> str:
        """Write content to path; return the stored path."""
        ...

    def get(self, path: str) -> bytes:
        """Read and return file contents; raise FileNotFoundError if not found."""
        ...

    def url(self, path: str) -> str:
        """Return a browser-accessible URL for the file."""
        ...

    def delete(self, path: str) -> None:
        """Delete file; idempotent (no error if not found)."""
        ...
