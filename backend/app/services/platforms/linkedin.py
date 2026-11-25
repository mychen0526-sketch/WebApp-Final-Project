"""LinkedIn: OAuth 2.0 (OpenID Connect) + Posts API on the member's own feed.

Docs:
- Sign In with LinkedIn using OpenID Connect: https://learn.microsoft.com/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
- Share on LinkedIn / Posts API: https://learn.microsoft.com/linkedin/marketing/community-management/shares/posts-api
- Images API: https://learn.microsoft.com/linkedin/marketing/community-management/shares/images-api

Unlike Threads / IG, LinkedIn does not fetch the picture from a URL: we download our own public
image, upload the bytes (initializeUpload → PUT), then create the post with the image URN.
- Commentary limit 3000 characters; tokens last 60 days and cannot be refreshed without the
  partner-only refresh-token program, so the user reconnects when it expires.
- `commentary` uses LinkedIn's "little text" format: reserved characters must be escaped, and
  hashtags are written as {hashtag|\\#|word}.
"""
import re
from urllib.parse import urlencode

import httpx

from ..webfetch import IMAGE_TYPES, FetchError, Fetcher, SafeFetcher, sniff_image
from .base import AccountToken, OAuthError, PublishError, PublishResult, TransientError, UncertainError, classify, expires_at

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
REVOKE_URL = "https://www.linkedin.com/oauth/v2/revoke"
USERINFO_URL ="https://api.linkedin.com/v2/userinfo"
REST = "https://api.linkedin.com/rest"
SCOPES = "openid profile w_member_social"
MAX_CHARS = 3000
MAX_IMAGE_BYTES = 8 * 1024 * 1024

_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_HASHTAG = re.compile(r"(?<!\S)#(\w+)")


def _escape(text: str) -> str:
    return _RESERVED.sub(r"\\\1", text)


def little_text(text: str) -> str:
    """Plain caption → LinkedIn little-text commentary (escaped, with real hashtags)."""
    out: list[str] = []
    pos = 0
    for match in _HASHTAG.finditer(text):
        out.append(_escape(text[pos : match.start()]))
        out.append("{hashtag|\\#|" + _escape(match.group(1)) + "}")
        pos = match.end()
    out.append(_escape(text[pos:]))
    return "".join(out)


def linkedin_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"LinkedIn HTTP {resp.status_code}: {resp.text[:300]}"
    if isinstance(body, dict):
        message = body.get("message") or body.get("error_description") or body.get("error")
        if message:
            return f"LinkedIn：{message}"
    return f"LinkedIn HTTP {resp.status_code}: {str(body)[:300]}"


class LinkedInPublisher:
    platform = "linkedin"
    is_mock = False

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        api_version: str = "202605",
        fetcher: Fetcher | None = None,
    ):
        # The picture is downloaded through the SSRF-safe fetcher: it only ever reaches public hosts,
        # so a crafted image URL cannot make the server read 169.254.169.254 or the private network.
        self.fetcher = fetcher or SafeFetcher(timeout=30)
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.version = api_version

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": SCOPES,
                "state": state,
            }
        )
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> AccountToken:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                },
            )
            if resp.status_code >= 400:
                raise OAuthError(linkedin_error(resp))
            token_data = resp.json()
            token = token_data["access_token"]
            me = client.get(USERINFO_URL, headers={"Authorization": f"Bearer {token}"})
            if me.status_code >= 400:
                raise OAuthError(linkedin_error(me))
            info = me.json()
        if not info.get("sub"):
            raise OAuthError("LinkedIn 沒有回傳會員 ID，請確認 App 已啟用 OpenID Connect")
        return AccountToken(
            platform_user_id=str(info["sub"]),
            username=info.get("name") or info.get("given_name"),
            access_token=token,
            token_expires_at=expires_at(token_data.get("expires_in")),
        )

    def revoke(self, account: dict) -> None:
        """Invalidate the token at LinkedIn when the user disconnects (best effort)."""
        with httpx.Client(timeout=15) as client:
            client.post(
                REVOKE_URL,
                data={"client_id": self.client_id, "client_secret": self.client_secret, "token": account["access_token"]},
            )

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": self.version,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def _call(self, request, *, final: bool = False) -> httpx.Response:
        try:
            resp = request()
        except httpx.TransportError as exc:
            if final:
                raise UncertainError(f"LinkedIn 沒有回應（{exc.__class__.__name__}），貼文可能已經發出") from exc
            raise TransientError(f"連不上 LinkedIn（{exc.__class__.__name__}），請稍後重試") from exc
        if resp.status_code >= 400:
            if final and resp.status_code >= 500:
                raise UncertainError(f"LinkedIn 回應錯誤（HTTP {resp.status_code}），貼文可能已經發出")
            raise classify(resp, linkedin_error(resp))
        return resp

    def _download(self, image_url: str) -> tuple[bytes, str]:
        try:
            picture = self.fetcher.get(image_url, MAX_IMAGE_BYTES, accept=tuple(IMAGE_TYPES))
        except FetchError as exc:
            raise PublishError(f"讀不到要發布的圖片（{exc}）") from exc
        content_type = sniff_image(picture.data)
        if content_type not in ("image/png", "image/jpeg"):
            raise PublishError("要發布的圖片不是 PNG 或 JPEG")
        return picture.data, content_type

    def _upload_image(self, client: httpx.Client, token: str, owner: str, image_url: str) -> str:
        data, content_type = self._download(image_url)
        init = self._call(
            lambda: client.post(
                f"{REST}/images?action=initializeUpload",
                json={"initializeUploadRequest": {"owner": owner}},
                headers=self._headers(token),
            )
        )
        value = init.json().get("value") or {}
        upload_url, image_urn = value.get("uploadUrl"), value.get("image")
        if not upload_url or not image_urn:
            raise PublishError("LinkedIn 沒有回傳圖片上傳網址")
        self._call(
            lambda: client.put(
                upload_url, content=data, headers={"Authorization": f"Bearer {token}", "Content-Type": content_type}
            )
        )
        return image_urn

    def publish(self, account: dict, caption: str, image_url: str | None) -> PublishResult:
        token = account["access_token"]
        owner = f"urn:li:person:{account['platform_user_id']}"
        if not caption and not image_url:
            raise PublishError("LinkedIn 貼文沒有文字也沒有圖片")
        if len(caption or "") > MAX_CHARS:
            raise PublishError(f"LinkedIn 文案超過 {MAX_CHARS} 字")
        with httpx.Client(timeout=60) as client:
            body: dict = {
                "author": owner,
                "commentary": little_text(caption or ""),
                "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }
            image_urn = None
            if image_url:
                image_urn = self._upload_image(client, token, owner, image_url)
                body["content"] = {"media": {"id": image_urn, "altText": (caption or "").split("\n")[0][:120]}}
            resp = self._call(lambda: client.post(f"{REST}/posts", json=body, headers=self._headers(token)), final=True)
            post_urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id")
            if not post_urn:
                # 201 without an id: the post exists but we cannot link to it
                raise UncertainError("LinkedIn 已接受貼文但沒有回傳貼文 ID，請到 LinkedIn 確認")
        return PublishResult(
            external_post_id=post_urn,
            permalink=f"https://www.linkedin.com/feed/update/{post_urn}/",
            container_id=image_urn,
        )
