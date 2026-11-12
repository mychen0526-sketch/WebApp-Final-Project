"""Threads API: OAuth + two-step publish (container → threads_publish).

Docs: https://developers.facebook.com/docs/threads
- Text limit 500 characters; 250 API posts per 24h per account.
- Images must be on a public URL.
"""
from urllib.parse import urlencode

import httpx

from .base import AccountToken, OAuthError, PublishError, PublishResult, check, expires_at, wait_for_container

AUTH_URL = "https://threads.net/oauth/authorize"
GRAPH = "https://graph.threads.net"
SCOPES = "threads_basic,threads_content_publish"


class ThreadsPublisher:
    platform = "threads"
    is_mock = False

    def __init__(self, app_id: str, app_secret: str, redirect_uri: str, poll_attempts: int = 10, poll_interval: float = 3.0):
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri
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
        with httpx.Client(timeout=30) as client:
            short = check(
                client.post(
                    f"{GRAPH}/oauth/access_token",
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
            long = check(
                client.get(
                    f"{GRAPH}/access_token",
                    params={
                        "grant_type": "th_exchange_token",
                        "client_secret": self.app_secret,
                        "access_token": short["access_token"],
                    },
                ),
                OAuthError,
            )
            token = long["access_token"]
            me = check(client.get(f"{GRAPH}/v1.0/me", params={"fields": "id,username", "access_token": token}), OAuthError)
        return AccountToken(
            platform_user_id=str(me.get("id") or short.get("user_id")),
            username=me.get("username"),
            access_token=token,
            token_expires_at=expires_at(long.get("expires_in")),
        )

    def publish(self, account: dict, caption: str, image_url: str | None) -> PublishResult:
        uid = account["platform_user_id"]
        token = account["access_token"]
        params = {"text": caption or "", "access_token": token}
        if image_url:
            params.update(media_type="IMAGE", image_url=image_url)
        else:
            if not caption:
                raise PublishError("Threads 貼文沒有文字也沒有圖片")
            params["media_type"] = "TEXT"
        with httpx.Client(timeout=30) as client:
            container_id = check(client.post(f"{GRAPH}/v1.0/{uid}/threads", params=params))["id"]
            wait_for_container(
                client, f"{GRAPH}/v1.0/{container_id}", token, "status", self.poll_attempts, self.poll_interval
            )
            media_id = check(
                client.post(f"{GRAPH}/v1.0/{uid}/threads_publish", params={"creation_id": container_id, "access_token": token})
            )["id"]
            permalink = None
            try:
                permalink = check(client.get(f"{GRAPH}/v1.0/{media_id}", params={"fields": "permalink", "access_token": token})).get(
                    "permalink"
                )
            except PublishError:
                pass  # the post is live; a missing link is not a failure
        return PublishResult(external_post_id=str(media_id), permalink=permalink, container_id=str(container_id))
