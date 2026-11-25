"""Fetch third-party pages and pictures (news articles, their lead images) without SSRF.

Every URL here comes from search results or article HTML, i.e. from strangers. Before each
request (and each redirect hop) the host must resolve only to public addresses, so a crafted
link cannot make the server call 127.0.0.1, the cloud metadata endpoint or the private network.
Bodies are size-capped and read as a stream.
"""
import ipaddress
import os
import socket
import ssl
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; OrbitStudioBot/1.0; +social-post-preview)"
MAX_REDIRECTS = 4
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class FetchError(RuntimeError):
    pass


@dataclass
class Fetched:
    url: str  # final URL after redirects
    content_type: str
    data: bytes


class Fetcher(Protocol):
    def get(self, url: str, max_bytes: int, accept: tuple[str, ...] = ()) -> Fetched: ...


def _public_host(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("只接受 http(s) 網址")
    if parts.port not in (None, 80, 443):
        raise FetchError("不接受非標準連接埠")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"找不到主機 {parts.hostname}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise FetchError("拒絕連到內部網路位址")


def _check_peer(resp: httpx.Response) -> None:
    """DNS rebinding: the name may resolve to a public IP for _public_host and to 127.0.0.1 a moment
    later when httpx connects. Check the address the connection actually reached before reading
    any of the body. (Skipped when the server itself goes through a configured HTTP proxy.)"""
    stream = resp.extensions.get("network_stream")
    if stream is None or _PROXY_CONFIGURED:
        return
    peer = stream.get_extra_info("server_addr")
    if not peer:
        return
    try:
        address = ipaddress.ip_address(str(peer[0]).split("%")[0])
    except ValueError:
        return
    if not address.is_global:
        raise FetchError("拒絕連到內部網路位址")


_PROXY_CONFIGURED = any(os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"))


class _NoAlpnContext(ssl.SSLContext):
    """httpcore always offers ALPN "http/1.1" in the TLS handshake. Bing's edge treats that
    fingerprint as a bot and serves a degraded news feed: empty for "SpaceX", loosely matched
    unrelated stories for longer queries. Without ALPN the server just speaks HTTP/1.1, which
    is all this client uses anyway, and returns the same results a browser or curl gets."""

    def set_alpn_protocols(self, protocols) -> None:  # noqa: ARG002 - deliberately ignored
        return None


def _tls_context() -> ssl.SSLContext:
    ctx = _NoAlpnContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_default_certs()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except ImportError:  # pragma: no cover - certifi ships with httpx
        pass
    return ctx


class SafeFetcher:
    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._tls = _tls_context()

    def get(self, url: str, max_bytes: int, accept: tuple[str, ...] = ()) -> Fetched:
        headers = {"User-Agent": USER_AGENT, "Accept": ",".join(accept) or "*/*"}
        with httpx.Client(timeout=self.timeout, follow_redirects=False, headers=headers, verify=self._tls) as client:
            for _ in range(MAX_REDIRECTS + 1):
                _public_host(url)
                try:
                    with client.stream("GET", url) as resp:
                        _check_peer(resp)
                        if resp.is_redirect:
                            location = resp.headers.get("location")
                            if not location:
                                raise FetchError("轉址沒有目的地")
                            url = urljoin(url, location)
                            continue
                        if resp.status_code >= 400:
                            raise FetchError(f"HTTP {resp.status_code}")
                        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                        if accept and not content_type.startswith(accept):
                            raise FetchError(f"內容類型不符：{content_type or '未知'}")
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in resp.iter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise FetchError("檔案太大")
                            chunks.append(chunk)
                        return Fetched(url=str(resp.url), content_type=content_type, data=b"".join(chunks))
                except httpx.HTTPError as exc:
                    raise FetchError(f"連線失敗：{exc.__class__.__name__}") from exc
        raise FetchError("轉址次數過多")


def sniff_image(data: bytes) -> str | None:
    """Content type from magic bytes (servers often send the wrong header)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
