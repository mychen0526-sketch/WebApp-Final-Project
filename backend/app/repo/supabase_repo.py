"""Supabase (PostgREST) repo using the service-role key.

The service role bypasses RLS, so every post query filters by user_id here.
Conditional updates (`.in_("status", expected)`) run as a single UPDATE ... WHERE,
which Postgres applies atomically per row.
"""
from collections.abc import Iterable

from supabase import Client


class SupabaseRepo:
    def __init__(self, client: Client) -> None:
        self.db = client

    # ---------- posts ----------
    def create_post(self, data: dict) -> dict:
        return self.db.table("posts").insert(data).execute().data[0]

    def get_post(self, user_id, post_id):
        rows = self.db.table("posts").select("*").eq("id", post_id).eq("user_id", user_id).limit(1).execute().data
        return rows[0] if rows else None

    def list_posts(self, user_id, status=None):
        query = self.db.table("posts").select("*").eq("user_id", user_id)
        if status:
            query = query.eq("status", status)
        return query.order("updated_at", desc=True).execute().data

    def update_post(self, user_id, post_id, changes, expected=None):
        query = self.db.table("posts").update(changes).eq("id", post_id).eq("user_id", user_id)
        if expected is not None:
            query = query.in_("status", [str(s) for s in expected])
        rows = query.execute().data
        return rows[0] if rows else None

    def delete_post(self, user_id, post_id, expected: Iterable[str]) -> bool:
        rows = (
            self.db.table("posts")
            .delete()
            .eq("id", post_id)
            .eq("user_id", user_id)
            .in_("status", [str(s) for s in expected])
            .execute()
            .data
        )
        return bool(rows)

    def claim_due_scheduled(self, now_iso_value):
        return (
            self.db.table("posts")
            .update({"status": "publishing"})
            .eq("status", "scheduled")
            .lte("scheduled_at", now_iso_value)
            .execute()
            .data
        )

    def fail_stale_generating(self, before_iso, message):
        rows = (
            self.db.table("posts")
            .update({"status": "generation_failed", "generation_error": message})
            .eq("status", "generating")
            .lt("updated_at", before_iso)
            .execute()
            .data
        )
        return len(rows)

    # ---------- images ----------
    def add_image(self, post_id, source, storage_path, public_url):
        row = {"post_id": post_id, "source": source, "storage_path": storage_path, "public_url": public_url}
        return self.db.table("post_images").insert(row).execute().data[0]

    def list_images(self, post_id):
        return self.db.table("post_images").select("*").eq("post_id", post_id).order("created_at").execute().data

    # ---------- templates ----------
    def add_template(self, user_id, data):
        return self.db.table("templates").insert({"user_id": user_id, **data}).execute().data[0]

    def list_templates(self, user_id):
        return self.db.table("templates").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data

    def get_template(self, user_id, template_id):
        rows = self.db.table("templates").select("*").eq("id", template_id).eq("user_id", user_id).limit(1).execute().data
        return rows[0] if rows else None

    def delete_template(self, user_id, template_id):
        rows = self.db.table("templates").delete().eq("id", template_id).eq("user_id", user_id).execute().data
        return bool(rows)

    # ---------- publications ----------
    def list_publications(self, post_id):
        return self.db.table("publications").select("*").eq("post_id", post_id).execute().data

    def upsert_publication(self, post_id, platform, changes):
        row = {"post_id": post_id, "platform": platform, **changes}
        return self.db.table("publications").upsert(row, on_conflict="post_id,platform").execute().data[0]

    # ---------- accounts ----------
    def list_accounts(self, user_id):
        return self.db.table("social_accounts").select("*").eq("user_id", user_id).execute().data

    def get_account(self, user_id, platform):
        rows = (
            self.db.table("social_accounts").select("*").eq("user_id", user_id).eq("platform", platform).execute().data
        )
        return rows[0] if rows else None

    def upsert_account(self, user_id, platform, data):
        row = {"user_id": user_id, "platform": platform, **data}
        return self.db.table("social_accounts").upsert(row, on_conflict="user_id,platform").execute().data[0]

    def delete_account(self, user_id, platform):
        rows = self.db.table("social_accounts").delete().eq("user_id", user_id).eq("platform", platform).execute().data
        return bool(rows)

    # ---------- settings / feedback ----------
    def get_settings(self, user_id):
        rows = self.db.table("user_settings").select("*").eq("user_id", user_id).execute().data
        return rows[0] if rows else None

    def upsert_settings(self, user_id, data):
        row = {"user_id": user_id, **data}
        return self.db.table("user_settings").upsert(row, on_conflict="user_id").execute().data[0]

    def add_feedback(self, user_id, post_id, rating):
        row = {"user_id": user_id, "post_id": post_id, "rating": rating}
        return self.db.table("generation_feedback").insert(row).execute().data[0]
