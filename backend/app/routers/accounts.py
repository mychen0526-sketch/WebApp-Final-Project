"""P2: social account binding (Threads / Instagram / LinkedIn OAuth). Tokens never leave the backend."""
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

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
PlatformParam = Literal["threads", "instagram", "linkedin"]
STATE_TTL = timedelta(minutes=10)


def _public(account: dict | None, platform: str) -> dict:
    if not account:
        return {"platform": platform, "connected": False, "username": None, "expired": False, "token_expires_at": None}
    expires = parse_ts(account.get("token_expires_at"))
    return {
        "platform": platform,
        "connected": True,
        "username": account.get("username"),
        "expired": bool(expires and expires <= utcnow()),
        "token_expires_at": account.get("token_expires_at"),
    }


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
        token = publisher.exchange_code("mock")
        services.repo.upsert_account(user_id, platform, token.as_row())
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
    services.repo.upsert_account(claims["sub"], platform, token.as_row())
    return _redirect(services, connected=platform)


@router.delete("/{platform}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(platform: PlatformParam, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    services.repo.delete_account(user_id, platform)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
