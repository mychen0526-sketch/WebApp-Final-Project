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
    """A platform rejected the post. The message is shown to the user on P6."""


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


def check(resp: httpx.Response, error_cls: type[Exception] = PublishError) -> dict:
    if resp.status_code >= 400:
        raise error_cls(graph_error(resp))
    return resp.json()


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
        data = check(client.get(url, params={"fields": f"{status_field},error_message", "access_token": token}))
        status = str(data.get(status_field) or "").upper()
        if status in ("FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(f"媒體處理失敗：{data.get('error_message') or status}")
        time.sleep(interval)
    raise PublishError("媒體容器處理逾時，請稍後重試")
