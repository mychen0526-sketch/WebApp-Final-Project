"""Image storage. Threads and IG fetch images from a public URL, so production uses the public
Supabase Storage bucket `post-images`. Paths are `<user_id>/<post_id>/<uuid>.<ext>`, matching the
"upload to own folder" storage policy.
"""
import threading
import uuid
from typing import Protocol


def image_path(user_id: str, post_id: str, ext: str = "png") -> str:
    return f"{user_id}/{post_id}/{uuid.uuid4().hex}.{ext}"


def template_path(user_id: str, ext: str = "png") -> str:
    return f"{user_id}/templates/{uuid.uuid4().hex}.{ext}"


class Storage(Protocol):
    def upload(self, path: str, data: bytes, content_type: str) -> str:
        """Store bytes and return the public URL."""
        ...


class SupabaseStorage:
    def __init__(self, client, bucket: str) -> None:
        self.bucket = client.storage.from_(bucket)

    def upload(self, path, data, content_type):
        self.bucket.upload(path, data, {"content-type": content_type, "upsert": "true"})
        return self.bucket.get_public_url(path)


class MemoryStorage:
    """Dev/test storage served by the app at /dev-files/<path>. Not reachable by Threads/IG."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.files: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def upload(self, path, data, content_type):
        with self._lock:
            self.files[path] = (data, content_type)
        return f"{self.base_url}/dev-files/{path}"

    def get(self, path: str) -> tuple[bytes, str] | None:
        return self.files.get(path)
