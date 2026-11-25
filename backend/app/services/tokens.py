"""Social-account access tokens are encrypted at rest (Fernet: AES-128-CBC + HMAC-SHA256).

`social_accounts.access_token` holds "enc:v1:<fernet token>". A leaked database dump or backup
alone does not expose working Threads / Instagram / LinkedIn tokens; the key lives only in the
server's environment (TOKEN_ENCRYPTION_KEY, or derived from APP_SECRET when that is not set).

Rows written before encryption existed are plain text: they are still readable, and are
re-encrypted the next time the account is saved (reconnect or token refresh).
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"


class TokenDecryptError(RuntimeError):
    """The stored token was encrypted with another key (the key was rotated or is wrong)."""


class TokenCipher:
    def __init__(self, key: str = "", app_secret: str = "") -> None:
        if key:
            raw = key.encode()
        else:
            # deterministic fallback so a deployment that only sets APP_SECRET still encrypts
            digest = hashlib.sha256(b"orbit-studio/social-token/v1:" + app_secret.encode()).digest()
            raw = base64.urlsafe_b64encode(digest)
        self._fernet = Fernet(raw)

    def seal(self, token: str) -> str:
        if not token or token.startswith(PREFIX):
            return token
        return PREFIX + self._fernet.encrypt(token.encode()).decode()

    def open(self, stored: str | None) -> str:
        if not stored or not stored.startswith(PREFIX):
            return stored or ""  # legacy plain-text row
        try:
            return self._fernet.decrypt(stored[len(PREFIX) :].encode()).decode()
        except InvalidToken as exc:
            raise TokenDecryptError("帳號授權無法解密（伺服器金鑰已更換），請重新連結") from exc

    def seal_row(self, row: dict) -> dict:
        out = dict(row)
        if out.get("access_token"):
            out["access_token"] = self.seal(out["access_token"])
        return out

    def open_row(self, row: dict) -> dict:
        out = dict(row)
        out["access_token"] = self.open(out.get("access_token"))
        return out
