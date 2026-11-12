"""Background loop: publish scheduled posts when due, and fail generations that got stuck (E1)."""
import asyncio
import logging
from datetime import timedelta

from ..timeutil import utcnow
from .publishing import publish_post

log = logging.getLogger(__name__)


def run_due_once(services) -> int:
    """Claim (scheduled → publishing, atomic) and publish every due post. Returns how many ran."""
    repo = services.repo
    stale_before = (utcnow() - timedelta(minutes=services.settings.generation_stale_minutes)).isoformat()
    repo.fail_stale_generating(stale_before, "生成逾時，請重試")

    claimed = repo.claim_due_scheduled(utcnow().isoformat())
    for post in claimed:
        try:
            publish_post(services, post)
        except Exception:  # noqa: BLE001
            log.exception("scheduled publish failed for post %s", post["id"])
    return len(claimed)


async def scheduler_loop(services) -> None:
    interval = services.settings.scheduler_interval_seconds
    while True:
        try:
            await asyncio.to_thread(run_due_once, services)
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
