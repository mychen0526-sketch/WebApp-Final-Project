"""In-memory repo for tests and offline development. Not persistent."""
import copy
import threading
import uuid
from collections.abc import Iterable

from ..timeutil import now_iso, parse_ts

POST_DEFAULTS = {
    "title": None,
    "goal": "",
    "tone": None,
    "audience": None,
    "prompt_candidates": None,
    "selected_prompt": None,
    "caption_threads": None,
    "caption_instagram": None,
    "canvas_json": None,
    "versions": [],
    "status": "generating",
    "platforms": [],
    "generation_error": None,
    "approved_at": None,
    "scheduled_at": None,
}


class MemoryRepo:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.posts: dict[str, dict] = {}
        self.images: list[dict] = []
        self.publications: list[dict] = []
        self.accounts: dict[tuple[str, str], dict] = {}
        self.settings: dict[str, dict] = {}
        self.feedback: list[dict] = []
        self.templates: dict[str, dict] = {}

    # ---------- posts ----------
    def create_post(self, data: dict) -> dict:
        with self._lock:
            now = now_iso()
            post = {**POST_DEFAULTS, **copy.deepcopy(data), "id": str(uuid.uuid4()), "created_at": now, "updated_at": now}
            self.posts[post["id"]] = post
            return copy.deepcopy(post)

    def get_post(self, user_id: str, post_id: str) -> dict | None:
        with self._lock:
            post = self.posts.get(post_id)
            if not post or post["user_id"] != user_id:
                return None
            return copy.deepcopy(post)

    def list_posts(self, user_id: str, status: str | None = None) -> list[dict]:
        with self._lock:
            rows = [
                copy.deepcopy(p)
                for p in self.posts.values()
                if p["user_id"] == user_id and (status is None or p["status"] == status)
            ]
        return sorted(rows, key=lambda p: p["updated_at"], reverse=True)

    def update_post(self, user_id, post_id, changes, expected=None):
        with self._lock:
            post = self.posts.get(post_id)
            if not post or post["user_id"] != user_id:
                return None
            if expected is not None and post["status"] not in set(expected):
                return None
            post.update(copy.deepcopy(changes))
            post["updated_at"] = now_iso()
            return copy.deepcopy(post)

    def delete_post(self, user_id: str, post_id: str, expected: Iterable[str]) -> bool:
        with self._lock:
            post = self.posts.get(post_id)
            if not post or post["user_id"] != user_id or post["status"] not in set(expected):
                return False
            del self.posts[post_id]
            self.images = [i for i in self.images if i["post_id"] != post_id]
            self.publications = [p for p in self.publications if p["post_id"] != post_id]
            return True

    def claim_due_scheduled(self, now_iso_value: str) -> list[dict]:
        now = parse_ts(now_iso_value)
        claimed = []
        with self._lock:
            for post in self.posts.values():
                due = parse_ts(post["scheduled_at"])
                if post["status"] == "scheduled" and due and due <= now:
                    post["status"] = "publishing"
                    post["updated_at"] = now_iso()
                    claimed.append(copy.deepcopy(post))
        return claimed

    def fail_stale_generating(self, before_iso: str, message: str) -> int:
        before = parse_ts(before_iso)
        count = 0
        with self._lock:
            for post in self.posts.values():
                if post["status"] == "generating" and parse_ts(post["updated_at"]) < before:
                    post.update(status="generation_failed", generation_error=message, updated_at=now_iso())
                    count += 1
        return count

    # ---------- images ----------
    def add_image(self, post_id, source, storage_path, public_url):
        with self._lock:
            row = {
                "id": str(uuid.uuid4()),
                "post_id": post_id,
                "source": source,
                "storage_path": storage_path,
                "public_url": public_url,
                "created_at": now_iso(),
            }
            self.images.append(row)
            return dict(row)

    def list_images(self, post_id):
        with self._lock:
            return [dict(i) for i in self.images if i["post_id"] == post_id]

    # ---------- templates ----------
    def add_template(self, user_id, data):
        with self._lock:
            row = {"id": str(uuid.uuid4()), "user_id": user_id, "created_at": now_iso(), **copy.deepcopy(data)}
            self.templates[row["id"]] = row
            return dict(row)

    def list_templates(self, user_id):
        with self._lock:
            rows = [dict(t) for t in self.templates.values() if t["user_id"] == user_id]
        return sorted(rows, key=lambda t: t["created_at"], reverse=True)

    def get_template(self, user_id, template_id):
        with self._lock:
            row = self.templates.get(template_id)
            return dict(row) if row and row["user_id"] == user_id else None

    def delete_template(self, user_id, template_id):
        with self._lock:
            row = self.templates.get(template_id)
            if not row or row["user_id"] != user_id:
                return False
            del self.templates[template_id]
            return True

    # ---------- publications ----------
    def list_publications(self, post_id):
        with self._lock:
            return [dict(p) for p in self.publications if p["post_id"] == post_id]

    def upsert_publication(self, post_id, platform, changes):
        with self._lock:
            for row in self.publications:
                if row["post_id"] == post_id and row["platform"] == platform:
                    row.update(changes, updated_at=now_iso())
                    return dict(row)
            now = now_iso()
            row = {
                "id": str(uuid.uuid4()),
                "post_id": post_id,
                "platform": platform,
                "status": "pending",
                "container_id": None,
                "external_post_id": None,
                "permalink": None,
                "error_message": None,
                "published_at": None,
                "created_at": now,
                "updated_at": now,
                **changes,
            }
            self.publications.append(row)
            return dict(row)

    # ---------- accounts ----------
    def list_accounts(self, user_id):
        with self._lock:
            return [dict(a) for (uid, _), a in self.accounts.items() if uid == user_id]

    def get_account(self, user_id, platform):
        with self._lock:
            row = self.accounts.get((user_id, platform))
            return dict(row) if row else None

    def upsert_account(self, user_id, platform, data):
        with self._lock:
            now = now_iso()
            row = self.accounts.get((user_id, platform)) or {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "platform": platform,
                "created_at": now,
            }
            row.update(data, updated_at=now)
            self.accounts[(user_id, platform)] = row
            return dict(row)

    def delete_account(self, user_id, platform):
        with self._lock:
            return self.accounts.pop((user_id, platform), None) is not None

    # ---------- settings / feedback ----------
    def get_settings(self, user_id):
        with self._lock:
            row = self.settings.get(user_id)
            return copy.deepcopy(row) if row else None

    def upsert_settings(self, user_id, data):
        with self._lock:
            row = self.settings.setdefault(user_id, {"user_id": user_id})
            row.update(copy.deepcopy(data), updated_at=now_iso())
            return copy.deepcopy(row)

    def add_feedback(self, user_id, post_id, rating):
        with self._lock:
            row = {"id": str(uuid.uuid4()), "user_id": user_id, "post_id": post_id, "rating": rating, "created_at": now_iso()}
            self.feedback.append(row)
            return dict(row)
