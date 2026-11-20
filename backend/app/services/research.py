"""趨勢情報: search news / trend reports together with their real lead pictures.

Backends (SEARCH_BACKEND):
- tavily — Tavily Search API, `topic: news` (needs TAVILY_API_KEY). Recommended for production.
- rss    — Bing News RSS, free and keyless. Fine for a demo; its terms only allow showing the
           results, so use Tavily for anything public.
- mock   — fixed demo results, no network (tests, MOCK_AI).

Whatever the backend, each article's own page is read for its `og:image` (the picture the
publisher chose for sharing) and site name, so the picture and the credit come from the
original publisher. The search engine's thumbnail is only a fallback.

The picture is downloaded only when a post actually uses it (`fetch_picture`), and is then
normalized to a 1080×1080 JPEG so every platform accepts it and the canvas can export it.
"""
import html
import io
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import httpx

from ..schemas import Reference
from .webfetch import FetchError, Fetcher, SafeFetcher, sniff_image

log = logging.getLogger(__name__)

PAGE_BYTES = 768 * 1024  # og tags are in <head>; no need for the whole article
PICTURE_BYTES = 12 * 1024 * 1024
PICTURE_SIZE = 1080
MIN_PICTURE_SIDE = 320


class ResearchError(RuntimeError):
    pass


class Research(Protocol):
    name: str

    def search(self, query: str, limit: int = 8) -> list[Reference]: ...


# ---------------------------------------------------------------- article page metadata
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z_:.-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""")


def page_meta(page: str, base_url: str) -> dict:
    """og:image / twitter:image, og:site_name, og:description from an HTML page."""
    found: dict[str, str] = {}
    for tag in _META.findall(page):
        attrs = {m.group(1).lower(): html.unescape(m.group(3) or m.group(4) or m.group(5) or "") for m in _ATTR.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and attrs.get("content") and key not in found:
            found[key] = attrs["content"].strip()
    image = found.get("og:image:secure_url") or found.get("og:image") or found.get("twitter:image") or found.get("twitter:image:src")
    if image:
        image = urljoin(base_url, image)
        if not image.startswith(("http://", "https://")):
            image = None
    return {
        "image_url": image,
        "source": found.get("og:site_name") or "",
        "summary": found.get("og:description") or found.get("description") or "",
        "title": found.get("og:title") or "",
    }


def _host(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def _clip(text: str, size: int) -> str:
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()
    return text if len(text) <= size else text[: size - 1] + "…"


def enrich(fetcher: Fetcher, refs: list[Reference], workers: int = 6) -> list[Reference]:
    """Read each article page (in parallel) for the publisher's own picture, name and summary."""

    def one(ref: Reference) -> Reference:
        try:
            page = fetcher.get(ref.url, PAGE_BYTES, accept=("text/html", "application/xhtml"))
        except FetchError as exc:
            log.info("article page unavailable (%s): %s", exc, ref.url)
            return ref if ref.source else ref.model_copy(update={"source": _host(ref.url)})
        meta = page_meta(page.data.decode("utf-8", "replace"), page.url)
        return ref.model_copy(
            update={
                "url": page.url if page.url.startswith("http") else ref.url,
                "image_url": meta["image_url"] or ref.image_url,
                "source": ref.source or _clip(meta["source"], 120) or _host(page.url),
                "summary": ref.summary or _clip(meta["summary"], 600),
            }
        )

    if not refs:
        return refs
    with ThreadPoolExecutor(max_workers=min(workers, len(refs))) as pool:
        return list(pool.map(one, refs))


# ---------------------------------------------------------------- backends
def parse_markets(value: str | list[str] | tuple[str, ...]) -> list[str]:
    """"zh-TW,en-US" → ["zh-TW", "en-US"] (order kept, duplicates dropped)."""
    items = value.split(",") if isinstance(value, str) else value
    return list(dict.fromkeys(m.strip() for m in items if m and m.strip())) or ["zh-TW"]


def interleave(groups: list[list[Reference]], limit: int) -> list[Reference]:
    """Take one result from each market in turn, so both languages show up near the top."""
    out: list[Reference] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for row in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if row >= len(group):
                continue
            ref = group[row]
            title = re.sub(r"\W+", "", ref.title.lower())
            if ref.url in seen_urls or title in seen_titles:
                continue
            seen_urls.add(ref.url)
            seen_titles.add(title)
            out.append(ref)
            if len(out) >= limit:
                return out
    return out


class RssResearch:
    """Bing News RSS (keyless). Items carry a redirect link with the real URL in `url=`.

    Every configured market (SEARCH_MARKET, e.g. "zh-TW,en-US") is searched at once and the
    results are interleaved: a zh-TW feed alone indexes few English-language stories.
    """

    name = "rss"

    def __init__(self, fetcher: Fetcher, markets: str | list[str] = "zh-TW,en-US") -> None:
        self.fetcher = fetcher
        self.markets = parse_markets(markets)

    def search(self, query, limit=8):
        def one(market: str) -> list[Reference] | ResearchError:
            try:
                return self._search_market(query, limit, market)
            except ResearchError as exc:
                log.warning("news search failed for market %s: %s", market, exc)
                return exc

        with ThreadPoolExecutor(max_workers=len(self.markets)) as pool:
            found = list(pool.map(one, self.markets))
        groups = [g for g in found if not isinstance(g, ResearchError)]
        if not groups:  # every market failed: report the first reason
            raise found[0]
        return _prefer_publisher_pictures(self.fetcher, interleave(groups, limit))

    def _search_market(self, query: str, limit: int, market: str) -> list[Reference]:
        feed_url = f"https://www.bing.com/news/search?q={quote(query)}&format=rss&mkt={quote(market)}"
        try:
            feed = self.fetcher.get(feed_url, 2 * 1024 * 1024)
            root = ET.fromstring(feed.data)
        except (FetchError, ET.ParseError) as exc:
            raise ResearchError(f"新聞搜尋失敗：{exc}") from exc
        refs: list[Reference] = []
        for item in root.iter("item"):
            fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in item}
            link = fields.get("link", "")
            real = parse_qs(urlsplit(link).query).get("url", [link])[0]
            if not real.startswith(("http://", "https://")) or not fields.get("title"):
                continue
            thumb = fields.get("Image") or None
            if thumb:
                w, h = fields.get("ImageMaxWidth") or "1080", fields.get("ImageMaxHeight") or "1080"
                thumb = f"{thumb.replace('http://', 'https://', 1)}&w={w}&h={h}&c=14"
            published = None
            if fields.get("pubDate"):
                try:
                    published = parsedate_to_datetime(fields["pubDate"]).date().isoformat()
                except (TypeError, ValueError):
                    published = None
            refs.append(
                Reference(
                    title=_clip(fields["title"], 300),
                    url=real,
                    source=_clip(fields.get("Source", ""), 120),
                    published=published,
                    summary=_clip(fields.get("description", ""), 600),
                    image_url=thumb,
                )
            )
            if len(refs) >= limit:
                break
        return refs


class TavilyResearch:
    """https://docs.tavily.com/documentation/api-reference/endpoint/search"""

    name = "tavily"

    def __init__(self, api_key: str, fetcher: Fetcher, timeout: float = 20) -> None:
        self.api_key = api_key
        self.fetcher = fetcher
        self.timeout = timeout

    def search(self, query, limit=8):
        body = {
            "query": query,
            "topic": "news",
            "days": 30,
            "max_results": limit,
            "include_images": True,
            "include_image_descriptions": True,
        }
        try:
            resp = httpx.post(
                "https://api.tavily.com/search",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ResearchError(f"新聞搜尋失敗：{exc}") from exc
        if resp.status_code >= 400:
            raise ResearchError(f"新聞搜尋失敗（Tavily {resp.status_code}）：{resp.text[:200]}")
        data = resp.json()
        loose = [i.get("url") if isinstance(i, dict) else i for i in data.get("images") or []]
        loose = [u for u in loose if isinstance(u, str) and u.startswith("http")]
        refs = []
        for row in data.get("results") or []:
            url = row.get("url") or ""
            if not url.startswith(("http://", "https://")) or not row.get("title"):
                continue
            published = (row.get("published_date") or "")[:60] or None
            refs.append(
                Reference(
                    title=_clip(row["title"], 300),
                    url=url,
                    source=_host(url),
                    published=published,
                    summary=_clip(row.get("content", ""), 600),
                )
            )
        refs = enrich(self.fetcher, refs[:limit])
        # Tavily's image list is not tied to a result: only fill gaps, in order
        spare = iter(u for u in loose if u not in {r.image_url for r in refs})
        return [r if r.image_url else r.model_copy(update={"image_url": next(spare, None)}) for r in refs]


def _prefer_publisher_pictures(fetcher: Fetcher, refs: list[Reference]) -> list[Reference]:
    """Swap the search engine's thumbnail for the article's own og:image when the page has one."""
    thumbs = {r.url: r.image_url for r in refs}
    bare = [r.model_copy(update={"image_url": None}) for r in refs]
    return [r if r.image_url else r.model_copy(update={"image_url": thumbs.get(r.url)}) for r in enrich(fetcher, bare)]


class MockResearch:
    name = "mock"

    def search(self, query, limit=8):
        topic = query.strip()[:30]
        rows = [
            ("生成式 AI 加速企業產品開發", "示範新聞網", "整理企業如何用生成式 AI 加快開發、設計與業務流程。"),
            ("AI Agent 在新創的應用機會", "示範科技報", "Agent 技術如何幫中小型團隊擴大交付能力。"),
            ("2026 科技新創產業趨勢觀察", "示範市場研究", "市場轉向速度、AI 商業化與小團隊策略。"),
        ]
        return [
            Reference(
                title=f"{title}：{topic}",
                url=f"https://example.com/news/{index}",
                source=source,
                published="2026-11-18",
                summary=summary,
                image_url=f"https://picsum.photos/seed/orbit{index}/1200/800",
            )
            for index, (title, source, summary) in enumerate(rows[:limit], start=1)
        ]


def build_research(settings) -> Research | None:
    mode = settings.search_mode
    fetcher = SafeFetcher(timeout=6)
    if mode == "off":
        return None
    if mode == "mock":
        return MockResearch()
    if mode == "tavily" and settings.tavily_api_key:
        return TavilyResearch(settings.tavily_api_key, fetcher)
    return RssResearch(fetcher, settings.search_market)


# ---------------------------------------------------------------- the picture itself
def normalize_picture(data: bytes, size: int = PICTURE_SIZE) -> bytes:
    """Any JPEG/PNG/WebP → centre-cropped size×size RGB JPEG."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not sniff_image(data):
        raise ResearchError("這不是 JPEG / PNG / WebP 圖片")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            if min(img.size) < MIN_PICTURE_SIDE:
                raise ResearchError(f"圖片太小（{img.size[0]}×{img.size[1]}），至少要 {MIN_PICTURE_SIDE} px")
            img = ImageOps.fit(img.convert("RGB"), (size, size), Image.Resampling.LANCZOS, centering=(0.5, 0.42))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=88, optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise ResearchError(f"圖片無法讀取：{exc}") from exc


def fetch_picture(fetcher: Fetcher, url: str) -> bytes:
    try:
        got = fetcher.get(url, PICTURE_BYTES, accept=("image/", "application/octet-stream", "binary/octet-stream"))
    except FetchError as exc:
        raise ResearchError(f"下載新聞圖片失敗：{exc}") from exc
    return normalize_picture(got.data)
