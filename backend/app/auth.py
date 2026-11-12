"""Supabase JWT verification.

The frontend logs in with Supabase Auth and sends `Authorization: Bearer <access_token>`.
New Supabase projects sign tokens with asymmetric keys published at
`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`; older projects use the HS256 JWT secret.
Both are supported. In local dev without Supabase, DEV_AUTH=true allows `X-Dev-User: <id>`.
"""
from functools import lru_cache

import jwt
from fastapi import Depends, Header, Request

from .container import Services
from .errors import Unauthorized


def get_services(request: Request) -> Services:
    return request.app.state.services


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


def verify_token(token: str, services: Services) -> str:
    settings = services.settings
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise Unauthorized("伺服器未設定 SUPABASE_JWT_SECRET，無法驗證 HS256 token")
            key = settings.supabase_jwt_secret
        else:
            if not settings.supabase_url:
                raise Unauthorized("伺服器未設定 SUPABASE_URL，無法驗證 token")
            jwks = _jwks_client(f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")
            key = jwks.get_signing_key_from_jwt(token).key
        payload = jwt.decode(token, key, algorithms=[alg], audience="authenticated")
    except Unauthorized:
        raise
    except jwt.PyJWTError as exc:
        raise Unauthorized(f"登入憑證無效：{exc}") from exc
    sub = payload.get("sub")
    if not sub:
        raise Unauthorized("登入憑證缺少使用者 ID")
    return sub


def get_current_user(
    services: Services = Depends(get_services),
    authorization: str | None = Header(default=None),
    x_dev_user: str | None = Header(default=None),
) -> str:
    settings = services.settings
    if x_dev_user and settings.dev_auth and not settings.use_supabase:
        return x_dev_user
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("請先登入（缺少 Authorization: Bearer token）")
    return verify_token(authorization.split(" ", 1)[1].strip(), services)
