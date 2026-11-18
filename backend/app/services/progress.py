"""Live progress of background generations, for the SSE stream (GET /api/posts/{id}/stream).

In-process only: it lives as long as the server process. With several workers, or after a
restart, the stream falls back to reading the post status from the database.
"""
import re
import threading
import uuid
from dataclasses import dataclass, field, replace


class Cancelled(Exception):
    """Raised inside a generation that the user stopped (or that a newer run replaced)."""


@dataclass
class Progress:
    token: str
    stage: str = "copy"  # copy → card → image → save
    threads: str = ""  # Threads caption so far, while it is being written
    cancelled: bool = False
    done: bool = False
    version: int = 0  # bumps on every change so the stream only sends news


@dataclass
class ProgressHub:
    _items: dict[str, Progress] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, post_id: str) -> str:
        """Begin tracking a run; returns its token. A newer run replaces (and so stops) an older one."""
        token = uuid.uuid4().hex
        with self._lock:
            self._items[post_id] = Progress(token=token)
        return token

    def get(self, post_id: str) -> Progress | None:
        with self._lock:
            item = self._items.get(post_id)
            return replace(item) if item else None

    def update(self, post_id: str, token: str, **changes) -> None:
        """Record progress; raises Cancelled if this run was stopped or replaced."""
        with self._lock:
            item = self._items.get(post_id)
            if not item or item.token != token or item.cancelled:
                raise Cancelled()
            for key, value in changes.items():
                setattr(item, key, value)
            item.version += 1

    def cancel(self, post_id: str) -> None:
        with self._lock:
            item = self._items.get(post_id)
            if item:
                item.cancelled = True
                item.version += 1

    def finish(self, post_id: str, token: str) -> None:
        with self._lock:
            item = self._items.get(post_id)
            if item and item.token == token:
                item.done = True
                item.version += 1

    def forget(self, post_id: str) -> None:
        with self._lock:
            self._items.pop(post_id, None)


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "r": ""}


def partial_field(raw: str, key: str) -> str:
    """Best-effort value of a JSON string field from a reply that is still being written,
    e.g. '{"threads": "第一行\\n第二' → '第一行\n第二'."""
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*"', raw)
    if not match:
        return ""
    out: list[str] = []
    i = match.end()
    while i < len(raw):
        ch = raw[i]
        if ch == '"':
            break
        if ch == "\\":
            if i + 1 >= len(raw):
                break
            nxt = raw[i + 1]
            if nxt == "u":
                code = raw[i + 2 : i + 6]
                if len(code) < 4:
                    break
                try:
                    out.append(chr(int(code, 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append(_ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)
