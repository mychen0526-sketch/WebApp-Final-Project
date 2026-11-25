"""Publish an approved post to each selected platform (runs as a background task).

The caller has already moved the post to `publishing` with a compare-and-set, so only one worker
ever gets here per publish click (E5). Each platform gets its own `publications` row so that
"Threads OK, IG failed" becomes partially_published and a retry only touches the failed one (E6).

Failure handling, per platform (`publications.error_code`):
  sensitive      the user's sensitive words matched at publish time (also for scheduled posts and
                 retries, so a word added after approval still stops the post)
  not_connected  no account bound for this platform
  auth           token expired, revoked on the platform, or undecryptable: the account is flagged
                 (`social_accounts.auth_error`) so the UI asks the user to reconnect
  transient      5xx / 429 / network before anything went live; already retried here
                 `publish_transient_retries` times with a growing pause
  uncertain      the call that makes the post live got no answer. The post may exist, so a retry
                 first looks for it on the platform (find_recent) and only posts again when it is
                 not there; platforms that cannot be searched need the user's confirmation
  rejected       the platform said no (content, limits…): fix the post or try later
  internal       our own error (database, storage…)

Whatever happens, the post never stays in `publishing`: errors before the per-platform loop mark
every target failed, and the scheduler moves posts stuck in publishing (crashed worker) to
publish_failed with their unfinished platforms marked uncertain.
"""
import logging
import time
from datetime import timedelta

from ..state import Status
from ..timeutil import now_iso, parse_ts, utcnow
from .platforms.base import PublishError
from .tokens import TokenDecryptError

log = logging.getLogger(__name__)

# how far back to look for a post whose result we never received
LOOKUP_MARGIN = timedelta(minutes=15)


def publish_image_url(images: list[dict]) -> str | None:
    """Prefer the latest canvas export (has the text overlay); fall back to upload, template, AI image, news photo."""
    for source in ("exported", "uploaded", "template", "generated", "reference"):
        matches = [i for i in images if i["source"] == source]
        if matches:
            return max(matches, key=lambda i: i["created_at"])["public_url"]
    return None


CAPTION_FIELD = {"threads": "caption_threads", "instagram": "caption_instagram", "linkedin": "caption_linkedin"}


def caption_for(post: dict, platform: str) -> str:
    text = post.get(CAPTION_FIELD[platform]) or ""
    if platform == "linkedin" and not text:  # posts made before LinkedIn existed
        text = post.get("caption_instagram") or post.get("caption_threads") or ""
    return text


def final_status(platforms: list[str], publications: list[dict]) -> Status:
    by_platform = {p["platform"]: p["status"] for p in publications}
    ok = [p for p in platforms if by_platform.get(p) == "success"]
    if platforms and len(ok) == len(platforms):
        return Status.PUBLISHED
    return Status.PARTIALLY_PUBLISHED if ok else Status.PUBLISH_FAILED


def sensitive_hits(services, post: dict) -> list[str]:
    from ..routers.settings import load_settings  # local: routers import this module
    from . import safety

    words = load_settings(services, post["user_id"])["sensitive_words"]
    return safety.scan(safety.post_text(post), words)["detected"]


def can_look_up(publisher) -> bool:
    if not hasattr(publisher, "find_recent"):
        return False
    return getattr(publisher, "supports_lookup", True)


def unverifiable_uncertain(services, post_id: str, targets: list[str]) -> list[str]:
    """Targets whose last attempt may have gone live and whose platform cannot be searched."""
    rows = {p["platform"]: p for p in services.repo.list_publications(post_id)}
    return [
        platform
        for platform in targets
        if (rows.get(platform) or {}).get("error_code") == "uncertain"
        and not can_look_up(services.publishers.get(platform))
    ]


def _fail(repo, post_id: str, platform: str, message: str, code: str) -> None:
    repo.upsert_publication(post_id, platform, {"status": "failed", "error_message": message[:500], "error_code": code})


def _succeed(repo, post_id: str, platform: str, result, note: str | None = None) -> None:
    repo.upsert_publication(
        post_id,
        platform,
        {
            "status": "success",
            "external_post_id": result.external_post_id,
            "permalink": result.permalink,
            "container_id": result.container_id,
            "error_message": note,
            "error_code": None,
            "published_at": now_iso(),
        },
    )


def _account_for(services, user_id: str, platform: str) -> dict:
    account = services.repo.get_account(user_id, platform)
    if not account:
        raise PublishError("尚未綁定這個平台的帳號", "not_connected")
    if account.get("auth_error"):
        raise PublishError(f"帳號授權已失效，請重新連結：{account['auth_error']}", "auth")
    expires = parse_ts(account.get("token_expires_at"))
    if expires and expires <= utcnow():
        raise PublishError("帳號授權已過期，請重新連結", "auth")
    try:
        return services.tokens.open_row(account)
    except TokenDecryptError as exc:
        raise PublishError(str(exc), "auth") from exc


def _publish_with_retries(services, publisher, account: dict, caption: str, image_url: str | None):
    retries = max(0, services.settings.publish_transient_retries)
    backoff = services.settings.publish_retry_backoff_seconds
    for attempt in range(retries + 1):
        try:
            return publisher.publish(account, caption, image_url)
        except PublishError as exc:
            if exc.kind != "transient" or attempt == retries:
                raise
            log.info("transient error on %s (attempt %d): %s", publisher.platform, attempt + 1, exc)
            if backoff:
                time.sleep(backoff * (attempt + 1))
    raise AssertionError("unreachable")


def _publish_one(services, post: dict, platform: str, image_url: str | None, previous: dict | None, confirmed: set[str]):
    repo = services.repo
    post_id, user_id = post["id"], post["user_id"]
    publisher = services.publishers[platform]
    caption = caption_for(post, platform)
    try:
        account = _account_for(services, user_id, platform)
        if previous and previous.get("error_code") == "uncertain" and platform not in confirmed:
            since = (parse_ts(previous.get("updated_at")) or utcnow()) - LOOKUP_MARGIN
            if not can_look_up(publisher):
                raise PublishError(
                    "上一次發布沒有收到平台回應，貼文可能已經發出。請先到平台確認，確定沒有發出再重試", "uncertain"
                )
            try:
                found = publisher.find_recent(account, caption, since)
            except PublishError as exc:
                raise PublishError(f"無法確認上一次是否已發出（{exc}），請稍後重試", "uncertain") from exc
            if found:  # it went live last time: record it instead of posting twice
                _succeed(repo, post_id, platform, found, note="上一次的發布其實已成功，未重複發文")
                return
        result = _publish_with_retries(services, publisher, account, caption, image_url)
        _succeed(repo, post_id, platform, result)
    except PublishError as exc:
        if exc.kind == "auth":
            if repo.get_account(user_id, platform):
                repo.update_account(user_id, platform, {"auth_error": str(exc)[:300]})
        elif exc.kind == "uncertain":
            log.warning("publish result unknown for post %s on %s: %s", post_id, platform, exc)
        _fail(repo, post_id, platform, str(exc), exc.kind)
    except Exception as exc:  # noqa: BLE001 - one platform failing must not stop the others
        log.exception("unexpected error publishing post %s to %s", post_id, platform)
        _fail(repo, post_id, platform, f"系統錯誤：{exc}", "internal")


def publish_post(services, post: dict, targets: list[str] | None = None, confirmed: list[str] | None = None) -> Status:
    """`targets`: platforms to (re)try, default all. `confirmed`: platforms whose uncertain last
    attempt the user checked by hand and says did not go live (post again without searching)."""
    repo = services.repo
    user_id, post_id = post["user_id"], post["id"]
    platforms = list(post.get("platforms") or [])
    targets = [p for p in (targets or platforms) if p in platforms]
    confirmed_set = set(confirmed or [])
    try:
        previous = {p["platform"]: p for p in repo.list_publications(post_id)}
        for platform in targets:
            repo.upsert_publication(post_id, platform, {"status": "pending", "error_message": None, "error_code": None})

        hits = sensitive_hits(services, post)
        if hits:
            message = f"安全檢查未通過，偵測到敏感詞：{'、'.join(hits)}。請重新編輯後再送審"
            for platform in targets:
                _fail(repo, post_id, platform, message, "sensitive")
        else:
            image_url = publish_image_url(repo.list_images(post_id))
            for platform in targets:
                _publish_one(services, post, platform, image_url, previous.get(platform), confirmed_set)
    except Exception as exc:  # noqa: BLE001 - e.g. the database / storage failed before any platform ran
        log.exception("publishing post %s failed before or between platforms", post_id)
        try:
            done = {p["platform"] for p in repo.list_publications(post_id) if p["status"] in ("success", "failed")}
            for platform in targets:
                if platform not in done:
                    _fail(repo, post_id, platform, f"發布準備失敗：{exc}", "internal")
        except Exception:  # noqa: BLE001 - the stale-publishing sweep in the scheduler will finish the job
            log.exception("could not record the failure of post %s", post_id)

    try:
        status = final_status(platforms, repo.list_publications(post_id))
    except Exception:  # noqa: BLE001
        log.exception("could not read publications of post %s", post_id)
        status = Status.PUBLISH_FAILED
    repo.update_post(user_id, post_id, {"status": status.value}, expected={Status.PUBLISHING})
    return status


def recover_stale_publishing(services, before_iso: str) -> int:
    """Posts left in `publishing` (worker crashed, server restarted) → final status. Platforms
    that never reported back are marked uncertain: they might be live, so retry checks first."""
    repo = services.repo
    count = 0
    for post in repo.list_stale_publishing(before_iso):
        post_id = post["id"]
        for pub in repo.list_publications(post_id):
            if pub["status"] == "pending":
                _fail(
                    repo,
                    post_id,
                    pub["platform"],
                    "發布中斷（伺服器重新啟動或逾時），貼文可能已經發出；重試時會先確認",
                    "uncertain",
                )
        platforms = list(post.get("platforms") or [])
        status = final_status(platforms, repo.list_publications(post_id))
        if repo.update_post(post["user_id"], post_id, {"status": status.value}, expected={Status.PUBLISHING}):
            count += 1
    return count
