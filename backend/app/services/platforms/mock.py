"""Simulated publisher (MOCK_PUBLISH=true): full flow without Meta / LinkedIn app review (Milestone E11).

Tests use the knobs to inject platform failures:
  fail_with / fail_kind — raise PublishError(fail_with, kind) instead of posting
  fail_times            — only fail the next N calls (then succeed), e.g. one 503 then OK
  lose_response         — create the post but raise UncertainError, as if the answer was lost
  supports_lookup       — whether find_recent() is available (LinkedIn's real API has none)
"""
import uuid
from datetime import datetime

from ...timeutil import utcnow
from .base import AccountToken, PublishError, PublishResult, UncertainError, expires_at, same_caption


class MockPublisher:
    is_mock = True

    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.fail_with: str | None = None
        self.fail_kind: str = "rejected"
        self.fail_times: int | None = None
        self.lose_response = False
        self.supports_lookup = True
        self.calls: list[dict] = []
        self.remote: list[dict] = []  # posts that exist "on the platform"
        self.revoked: list[str] = []

    def configured(self) -> bool:
        return True

    def authorize_url(self, state: str) -> str:
        return f"mock://{self.platform}/authorize?state={state}"

    def exchange_code(self, code: str) -> AccountToken:
        return AccountToken(
            platform_user_id=f"mock-{self.platform}-user",
            username=f"demo_{self.platform}",
            access_token=f"mock-token-{uuid.uuid4().hex[:8]}",
            token_expires_at=expires_at(60 * 24 * 3600),
        )

    def refresh(self, account: dict) -> AccountToken:
        return AccountToken(
            platform_user_id=account["platform_user_id"],
            username=account.get("username"),
            access_token=f"mock-token-{uuid.uuid4().hex[:8]}",
            token_expires_at=expires_at(60 * 24 * 3600),
        )

    def revoke(self, account: dict) -> None:
        self.revoked.append(account["access_token"])

    def _result(self) -> PublishResult:
        post_id = uuid.uuid4().hex[:12]
        if self.platform == "linkedin":
            permalink = f"https://www.linkedin.com/feed/update/urn:li:share:mock-{post_id}/"
        else:
            host = "threads.net" if self.platform == "threads" else "instagram.com"
            permalink = f"https://www.{host}/p/mock-{post_id}"
        return PublishResult(external_post_id=f"mock-{post_id}", permalink=permalink, container_id=f"mock-container-{post_id}")

    def publish(self, account, caption, image_url):
        self.calls.append(
            {"account": account.get("username"), "token": account.get("access_token"), "caption": caption, "image_url": image_url}
        )
        if self.platform == "instagram" and not image_url:
            raise PublishError("Instagram 貼文一定要有圖片")
        if self.fail_with and (self.fail_times is None or self.fail_times > 0):
            if self.fail_times is not None:
                self.fail_times -= 1
            raise PublishError(self.fail_with, self.fail_kind)
        result = self._result()
        self.remote.append({"caption": caption, "result": result, "at": utcnow()})
        if self.lose_response:
            self.lose_response = False
            raise UncertainError()
        return result

    def find_recent(self, account, caption, since: datetime):
        if not self.supports_lookup:
            raise NotImplementedError
        for item in self.remote:
            if item["at"] >= since and same_caption(item["caption"], caption):
                return item["result"]
        return None
