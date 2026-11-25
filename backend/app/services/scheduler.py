"""Background loop, every SCHEDULER_INTERVAL_SECONDS:

1. fail generations that got stuck (E1);
2. finish posts stuck in `publishing` (worker crashed mid-publish) as publish_failed, with the
   platforms that never answered marked uncertain;
3. publish scheduled posts that are due (publish_post re-checks sensitive words, so a word added
   after scheduling still stops the post);
4. about once an hour, refresh Threads / Instagram tokens that expire soon. Tokens the platform
   refuses to refresh (revoked) are flagged so the UI asks the user to reconnect.
"""
import asyncio
import logging
import time
from datetime import timedelta

from ..timeutil import parse_ts, utcnow
from .platforms.base import OAuthError
from .publishing import publish_post, recover_stale_publishing

log = logging.getLogger(__name__)
TOKEN_REFRESH_EVERY_SECONDS = 3600


def refresh_expiring_tokens(services) -> int:
    """Extend long-lived tokens that expire within TOKEN_REFRESH_DAYS. Returns how many were renewed."""
    repo = services.repo
    before = (utcnow() + timedelta(days=services.settings.token_refresh_days)).isoformat()
    renewed = 0
    for account in repo.list_expiring_accounts(before):
        platform = account["platform"]
        publisher = services.publishers.get(platform)
        expires = parse_ts(account.get("token_expires_at"))
        if publisher is None or not hasattr(publisher, "refresh"):
            continue  # LinkedIn: no refresh without the partner program; GET /api/accounts says expiring_soon
        if expires and expires <= utcnow():
            continue  # already expired: only a new login helps
        try:
            token = publisher.refresh(services.tokens.open_row(account))
        except OAuthError as exc:
            repo.update_account(account["user_id"], platform, {"auth_error": f"無法自動續期授權：{exc}"[:300]})
            continue
        except Exception:  # noqa: BLE001 - network trouble: try again next sweep
            log.warning("token refresh failed for %s / %s", account["user_id"], platform, exc_info=True)
            continue
        repo.update_account(account["user_id"], platform, {**services.tokens.seal_row(token.as_row()), "auth_error": None})
        renewed += 1
    return renewed


def run_due_once(services, force_token_refresh: bool = False) -> int:
    """Claim (scheduled → publishing, atomic) and publish every due post. Returns how many ran."""
    repo = services.repo
    cfg = services.settings
    stale_before = (utcnow() - timedelta(minutes=cfg.generation_stale_minutes)).isoformat()
    repo.fail_stale_generating(stale_before, "生成逾時，請重試")

    try:
        recover_stale_publishing(services, (utcnow() - timedelta(minutes=cfg.publish_stale_minutes)).isoformat())
    except Exception:  # noqa: BLE001
        log.exception("recovering stuck publishing posts failed")

    claimed = repo.claim_due_scheduled(utcnow().isoformat())
    for post in claimed:
        try:
            publish_post(services, post)
        except Exception:  # noqa: BLE001
            log.exception("scheduled publish failed for post %s", post["id"])

    if force_token_refresh or time.monotonic() - services.last_token_refresh >= TOKEN_REFRESH_EVERY_SECONDS:
        services.last_token_refresh = time.monotonic()
        try:
            refresh_expiring_tokens(services)
        except Exception:  # noqa: BLE001
            log.exception("token refresh sweep failed")
    return len(claimed)


async def scheduler_loop(services) -> None:
    interval = services.settings.scheduler_interval_seconds
    while True:
        try:
            await asyncio.to_thread(run_due_once, services)
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
