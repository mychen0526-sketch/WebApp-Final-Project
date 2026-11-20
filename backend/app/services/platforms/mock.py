"""Simulated publisher (MOCK_PUBLISH=true): full flow without Meta / LinkedIn app review (Milestone E11)."""
import uuid

from .base import AccountToken, PublishError, PublishResult, expires_at


class MockPublisher:
    is_mock = True

    def __init__(self, platform: str) -> None:
        self.platform = platform
        self.fail_with: str | None = None  # tests set this to simulate a platform error
        self.calls: list[dict] = []

    def configured(self) -> bool:
        return True

    def authorize_url(self, state: str) -> str:
        return f"mock://{self.platform}/authorize?state={state}"

    def exchange_code(self, code: str) -> AccountToken:
        return AccountToken(
            platform_user_id=f"mock-{self.platform}-user",
            username=f"demo_{self.platform}",
            access_token="mock-token",
            token_expires_at=expires_at(60 * 24 * 3600),
        )

    def publish(self, account, caption, image_url):
        self.calls.append({"account": account.get("username"), "caption": caption, "image_url": image_url})
        if self.platform == "instagram" and not image_url:
            raise PublishError("Instagram 貼文一定要有圖片")
        if self.fail_with:
            raise PublishError(self.fail_with)
        post_id = uuid.uuid4().hex[:12]
        if self.platform == "linkedin":
            permalink = f"https://www.linkedin.com/feed/update/urn:li:share:mock-{post_id}/"
        else:
            host = "threads.net" if self.platform == "threads" else "instagram.com"
            permalink = f"https://www.{host}/p/mock-{post_id}"
        return PublishResult(
            external_post_id=f"mock-{post_id}",
            permalink=permalink,
            container_id=f"mock-container-{post_id}",
        )
