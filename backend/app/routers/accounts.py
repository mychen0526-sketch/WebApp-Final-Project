"""P2: social account binding (Threads / Instagram / LinkedIn OAuth). Tokens never leave the backend.

Tokens are encrypted before they are stored (services/tokens.py). An account "needs reconnect"
when its token has expired or a platform rejected it as revoked/invalid (`auth_error`); the
scheduler refreshes Threads / Instagram tokens before they expire. LinkedIn tokens cannot be
refreshed, so the account shows `expiring_soon` during its last days.
"""
import logging
from datetime import timedelta
from typing import Literal
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse

from ..auth import get_current_user, get_services
from ..container import Services
from ..errors import ServiceUnavailable
from ..schemas import PLATFORMS
from ..services.platforms.base import OAuthError
from ..timeutil import parse_ts, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accounts", tags=["accounts"])
PlatformParam = Literal["threads", "instagram", "linkedin"]
STATE_TTL = timedelta(minutes=10)
EXPIRING_SOON = timedelta(days=7)


def _public(account: dict | None, platform: str) -> dict:
    """What the frontend may see: never the token itself."""
    if not account:
        return {
            "platform": platform,
            "connected": False,
            "username": None,
            "expired": False,
            "needs_reconnect": False,
            "expiring_soon": False,
            "auth_error": None,
            "token_expires_at": None,
        }
    expires = parse_ts(account.get("token_expires_at"))
    now = utcnow()
    time_expired = bool(expires and expires <= now)
    auth_error = account.get("auth_error")
    return {
        "platform": platform,
        "connected": True,
        "username": account.get("username"),
        # `expired` also covers revoked tokens so the existing UI shows "授權已過期 → 重新連結"
        "expired": time_expired or bool(auth_error),
        "needs_reconnect": time_expired or bool(auth_error),
        "expiring_soon": bool(expires and not time_expired and expires - now <= EXPIRING_SOON),
        "auth_error": auth_error,
        "token_expires_at": account.get("token_expires_at"),
    }


def save_account(services: Services, user_id: str, platform: str, token) -> None:
    """Store a fresh token (encrypted) and clear any earlier authorization error."""
    services.repo.upsert_account(user_id, platform, {**services.tokens.seal_row(token.as_row()), "auth_error": None})


def _redirect(services: Services, **params) -> RedirectResponse:
    return RedirectResponse(f"{services.settings.frontend_url}?{urlencode(params)}", status_code=status.HTTP_302_FOUND)


@router.get("")
def list_accounts(user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    rows = {a["platform"]: a for a in services.repo.list_accounts(user_id)}
    return [_public(rows.get(p), p) for p in PLATFORMS]


@router.get("/{platform}/connect")
def connect(platform: PlatformParam, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """Return the official authorization URL. The frontend navigates there; the platform redirects to /callback."""
    publisher = services.publishers[platform]
    if publisher.is_mock:
        save_account(services, user_id, platform, publisher.exchange_code("mock"))
        return {"url": f"{services.settings.frontend_url}?{urlencode({'connected': platform})}", "mock": True}
    if not publisher.configured():
        raise ServiceUnavailable(f"伺服器尚未設定 {platform} 的 App ID / Secret")
    state = jwt.encode(
        {"sub": user_id, "platform": platform, "purpose": "oauth", "exp": utcnow() + STATE_TTL},
        services.settings.app_secret,
        algorithm="HS256",
    )
    return {"url": publisher.authorize_url(state), "mock": False}


@router.get("/{platform}/callback", include_in_schema=False)
def callback(
    platform: PlatformParam,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    services: Services = Depends(get_services),
):
    """OAuth redirect target (no JWT: the user is identified by the signed `state`)."""
    if not code or not state:
        return _redirect(services, connect_error=error_description or "授權已取消", platform=platform)
    try:
        claims = jwt.decode(state, services.settings.app_secret, algorithms=["HS256"])
        if claims.get("purpose") != "oauth" or claims.get("platform") != platform:
            raise jwt.InvalidTokenError("state mismatch")
    except jwt.PyJWTError:
        return _redirect(services, connect_error="授權連結無效或已過期，請重新連結", platform=platform)
    try:
        token = services.publishers[platform].exchange_code(code)
    except OAuthError as exc:
        return _redirect(services, connect_error=str(exc), platform=platform)
    save_account(services, claims["sub"], platform, token)
    return _redirect(services, connected=platform)


@router.delete("/{platform}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(platform: PlatformParam, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """Remove the binding. Where the platform supports it (LinkedIn) the token is also revoked
    there, so a copy of it is useless afterwards. Revocation is best effort: the local row is
    deleted even if the platform cannot be reached."""
    account = services.repo.get_account(user_id, platform)
    publisher = services.publishers.get(platform)
    if account and publisher is not None and hasattr(publisher, "revoke"):
        try:
            publisher.revoke(services.tokens.open_row(account))
        except Exception:  # noqa: BLE001
            log.warning("could not revoke %s token for user %s", platform, user_id, exc_info=True)
    services.repo.delete_account(user_id, platform)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
