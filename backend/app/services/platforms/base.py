"""Common publisher interface and the Graph-API container flow shared by Threads and Instagram.

Both platforms publish in two steps: create a media container from a public image URL, wait until
the container is FINISHED (Meta recommends waiting ~30s; we poll every few seconds, see E10), then
publish the container.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx


class PublishError(RuntimeError):
    """A platform rejected the post. The message is shown to the user on P6.

    `kind` tells the publisher loop and the user what to do next:
      rejected  — the platform said no (content, limits, missing image): fix the post, then retry
      auth      — the token is expired or was revoked by the user: reconnect the account
      transient — 5xx / 429 / network before anything was posted: safe to retry automatically
      uncertain — the request that creates the post was sent but no answer came back: the post may
                  be live, so a retry must check the platform first (never blindly post again)
    """

    def __init__(self, message: str, kind: str = "rejected") -> None:
        super().__init__(message)
        self.kind = kind


class AuthError(PublishError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "auth")


class TransientError(PublishError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "transient")


class UncertainError(PublishError):
    def __init__(self, message: str = "平台沒有回應，貼文可能已經發出") -> None:
        super().__init__(message, "uncertain")


class OAuthError(RuntimeError):
    pass


@dataclass
class AccountToken:
    platform_user_id: str
    username: str | None
    access_token: str
    token_expires_at: str | None  # ISO timestamp

    def as_row(self) -> dict:
        return {
            "platform_user_id": self.platform_user_id,
            "username": self.username,
            "access_token": self.access_token,
            "token_expires_at": self.token_expires_at,
        }


@dataclass
class PublishResult:
    external_post_id: str
    permalink: str | None
    container_id: str | None


class Publisher(Protocol):
    platform: str
    is_mock: bool

    def configured(self) -> bool: ...
    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> AccountToken: ...
    def publish(self, account: dict, caption: str, image_url: str | None) -> PublishResult: ...
    # Optional:
    #   find_recent(account, caption, since: datetime) -> PublishResult | None
    #       look for a post we may already have made (used before retrying an "uncertain" one)
    #   refresh(account) -> AccountToken
    #       extend a long-lived token before it expires


def expires_at(seconds: int | None) -> str | None:
    if not seconds:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=int(seconds))).isoformat()


def graph_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return err.get("error_user_msg") or err.get("message") or str(err)
    if isinstance(body, dict) and body.get("error_message"):
        return str(body["error_message"])
    return f"HTTP {resp.status_code}: {str(body)[:300]}"


def is_auth_failure(resp: httpx.Response) -> bool:
    """Meta: OAuthException / code 190 (expired, revoked, password changed); anyone: HTTP 401."""
    if resp.status_code == 401:
        return True
    try:
        err = resp.json().get("error")
    except (ValueError, AttributeError):
        return False
    return isinstance(err, dict) and (err.get("code") in (190, 102) or err.get("type") == "OAuthException")


def classify(resp: httpx.Response, message: str) -> PublishError:
    if is_auth_failure(resp):
        return AuthError(f"帳號授權已失效（可能已過期或在平台上被撤銷），請重新連結：{message}")
    if resp.status_code == 429 or resp.status_code >= 500:
        return TransientError(message)
    return PublishError(message)


def check(resp: httpx.Response, error_cls: type[Exception] = PublishError) -> dict:
    if resp.status_code >= 400:
        message = graph_error(resp)
        if error_cls is PublishError:
            raise classify(resp, message)
        raise error_cls(message)
    return resp.json()


def send(request, *, final: bool = False) -> dict:
    """Run one HTTP call and return its JSON. `final` marks the call that makes the post live:
    if it times out or the platform answers 5xx we cannot know whether the post exists, so that
    becomes UncertainError instead of a plain failure (see publishing.retry)."""
    try:
        resp = request()
    except httpx.TransportError as exc:
        name = exc.__class__.__name__
        if final:
            raise UncertainError(f"發布請求已送出但沒有收到平台回應（{name}），貼文可能已經發出") from exc
        raise TransientError(f"連不上平台（{name}），請稍後重試") from exc
    if final and resp.status_code >= 500:
        raise UncertainError(f"平台回應錯誤（HTTP {resp.status_code}），貼文可能已經發出")
    return check(resp)


def same_caption(a: str | None, b: str | None) -> bool:
    """Captions as the platform stores them may differ in whitespace / trailing newlines."""
    return " ".join((a or "").split())[:200] == " ".join((b or "").split())[:200]


def wait_for_container(
    client: httpx.Client,
    url: str,
    token: str,
    status_field: str,
    attempts: int,
    interval: float,
) -> None:
    """Poll a media container until FINISHED. ERROR/EXPIRED or timeout raise PublishError."""
    for _ in range(attempts):
        data = send(lambda: client.get(url, params={"fields": f"{status_field},error_message", "access_token": token}))
        status = str(data.get(status_field) or "").upper()
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(f"媒體處理失敗：{data.get('error_message') or status}")
        time.sleep(interval)
    raise PublishError("媒體容器處理逾時，請稍後重試")
