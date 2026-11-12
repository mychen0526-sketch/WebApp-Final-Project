"""Instagram API with Instagram Login: OAuth + two-step publish (media → media_publish).

Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
- Only professional (Business / Creator) accounts; no Facebook Page needed with Instagram Login.
- Every post needs an image (no text-only posts); 50 API posts per 24h per account.
"""
from urllib.parse import urlencode

import httpx

from .base import AccountToken, OAuthError, PublishError, PublishResult, check, expires_at, wait_for_container

AUTH_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
SCOPES = "instagram_business_basic,instagram_business_content_publish"


class InstagramPublisher:
    platform = "instagram"
    is_mock = False

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        redirect_uri: str,
        api_version: str = "v23.0",
        poll_attempts: int = 10,
        poll_interval: float = 3.0,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri
        self.version = api_version
        self.poll_attempts = poll_attempts
        self.poll_interval = poll_interval

    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.app_id,
                "redirect_uri": self.redirect_uri,
                "scope": SCOPES,
                "response_type": "code",
                "state": state,
            }
        )
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> AccountToken:
        code = code.split("#")[0]  # Instagram appends "#_" to the code
        with httpx.Client(timeout=30) as client:
            short = check(
                client.post(
                    TOKEN_URL,
                    data={
                        "client_id": self.app_id,
                        "client_secret": self.app_secret,
                        "grant_type": "authorization_code",
                        "redirect_uri": self.redirect_uri,
                        "code": code,
                    },
                ),
                OAuthError,
            )
            if isinstance(short.get("data"), list) and short["data"]:
                short = short["data"][0]
            long = check(
                client.get(
                    f"{GRAPH}/access_token",
                    params={
                        "grant_type": "ig_exchange_token",
                        "client_secret": self.app_secret,
                        "access_token": short["access_token"],
                    },
                ),
                OAuthError,
            )
            token = long["access_token"]
            me = check(
                client.get(
                    f"{GRAPH}/{self.version}/me",
                    params={"fields": "user_id,username,account_type", "access_token": token},
                ),
                OAuthError,
            )
        account_type = str(me.get("account_type") or "").upper()
        if account_type and account_type not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR"):
            raise OAuthError("這個 IG 帳號不是專業帳號（商業或創作者），請先在 IG 設定中轉換為專業帳號")
        return AccountToken(
            platform_user_id=str(me.get("user_id") or short.get("user_id")),
            username=me.get("username"),
            access_token=token,
            token_expires_at=expires_at(long.get("expires_in")),
        )

    def publish(self, account: dict, caption: str, image_url: str | None) -> PublishResult:
        if not image_url:
            raise PublishError("Instagram 貼文一定要有圖片")
        uid = account["platform_user_id"]
        token = account["access_token"]
        base = f"{GRAPH}/{self.version}"
        with httpx.Client(timeout=30) as client:
            container_id = check(
                client.post(f"{base}/{uid}/media", params={"image_url": image_url, "caption": caption or "", "access_token": token})
            )["id"]
            wait_for_container(client, f"{base}/{container_id}", token, "status_code", self.poll_attempts, self.poll_interval)
            media_id = check(
                client.post(f"{base}/{uid}/media_publish", params={"creation_id": container_id, "access_token": token})
            )["id"]
            permalink = None
            try:
                permalink = check(client.get(f"{base}/{media_id}", params={"fields": "permalink", "access_token": token})).get(
                    "permalink"
                )
            except PublishError:
                pass
        return PublishResult(external_post_id=str(media_id), permalink=permalink, container_id=str(container_id))
