"""Publish an approved post to each selected platform (runs as a background task).

The caller has already moved the post to `publishing` with a compare-and-set, so only one worker
ever gets here per publish click (E5). Each platform gets its own `publications` row so that
"Threads OK, IG failed" becomes partially_published and a retry only touches the failed one (E6).
"""
import logging

from ..state import Status
from ..timeutil import now_iso, parse_ts, utcnow
from .platforms.base import PublishError

log = logging.getLogger(__name__)


def publish_image_url(images: list[dict]) -> str | None:
    """Prefer the latest canvas export (has the text overlay); fall back to upload, template, then AI image."""
    for source in ("exported", "uploaded", "template", "generated"):
        matches = [i for i in images if i["source"] == source]
        if matches:
            return max(matches, key=lambda i: i["created_at"])["public_url"]
    return None


def caption_for(post: dict, platform: str) -> str:
    return (post.get("caption_threads") if platform == "threads" else post.get("caption_instagram")) or ""


def final_status(platforms: list[str], publications: list[dict]) -> Status:
    by_platform = {p["platform"]: p["status"] for p in publications}
    ok = [p for p in platforms if by_platform.get(p) == "success"]
    if len(ok) == len(platforms):
        return Status.PUBLISHED
    return Status.PARTIALLY_PUBLISHED if ok else Status.PUBLISH_FAILED


def publish_post(services, post: dict, targets: list[str] | None = None) -> Status:
    repo = services.repo
    user_id, post_id = post["user_id"], post["id"]
    platforms = list(post.get("platforms") or [])
    targets = [p for p in (targets or platforms) if p in platforms]
    image_url = publish_image_url(repo.list_images(post_id))

    for platform in targets:
        repo.upsert_publication(post_id, platform, {"status": "pending", "error_message": None})

    for platform in targets:
        try:
            account = repo.get_account(user_id, platform)
            if not account:
                raise PublishError("尚未綁定這個平台的帳號")
            expires = parse_ts(account.get("token_expires_at"))
            if expires and expires <= utcnow():
                raise PublishError("帳號授權已過期，請重新連結")
            publisher = services.publishers[platform]
            result = publisher.publish(account, caption_for(post, platform), image_url)
            repo.upsert_publication(
                post_id,
                platform,
                {
                    "status": "success",
                    "external_post_id": result.external_post_id,
                    "permalink": result.permalink,
                    "container_id": result.container_id,
                    "error_message": None,
                    "published_at": now_iso(),
                },
            )
        except Exception as exc:  # noqa: BLE001 - one platform failing must not stop the others
            if not isinstance(exc, PublishError):
                log.exception("unexpected error publishing post %s to %s", post_id, platform)
            repo.upsert_publication(post_id, platform, {"status": "failed", "error_message": str(exc)[:500]})

    status = final_status(platforms, repo.list_publications(post_id))
    repo.update_post(user_id, post_id, {"status": status.value}, expected={Status.PUBLISHING})
    return status
