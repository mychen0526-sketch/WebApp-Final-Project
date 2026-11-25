import json

import httpx
import pytest

from app.schemas import Reference
from app.services import design
from app.services.images import FluxImageAI
from app.services.platforms import linkedin as li
from app.services.research import RssResearch, normalize_picture, page_meta
from app.services.webfetch import FetchError, SafeFetcher

from .conftest import PNG, CANDIDATE, FakeFetcher, connect, create_post, export_card, jpeg_bytes, to_approved

PHOTO = "https://news.example.com/lead.jpg"
REFERENCE = {
    "title": "AI 新創拚 90 天拿下付費案",
    "url": "https://news.example.com/story/1",
    "source": "示範新聞網",
    "summary": "AI 新創可用 90 天完成客戶願意付費的應用。",
    "image_url": PHOTO,
}


# ---------------------------------------------------------------- LinkedIn
def test_little_text_escapes_reserved_and_keeps_hashtags():
    text = "新功能 (beta) 上線 @團隊 #AI #產業趨勢\n價格 [待定] a_b"
    out = li.little_text(text)
    assert "\\(beta\\)" in out and "\\@團隊" in out and "\\[待定\\]" in out and "a\\_b" in out
    assert "{hashtag|\\#|AI}" in out and "{hashtag|\\#|產業趨勢}" in out
    assert li.little_text("C# 很好") == "C\\# 很好"  # not a hashtag: no space before #


def test_linkedin_publish_uploads_image_then_posts(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.url.path == "/rest/images":
            assert request.headers["LinkedIn-Version"] == "202605"
            body = json.loads(request.content)
            assert body["initializeUploadRequest"]["owner"] == "urn:li:person:abc"
            return httpx.Response(200, json={"value": {"uploadUrl": "https://upload.example.com/u", "image": "urn:li:image:9"}})
        if request.url.host == "upload.example.com":
            assert request.content == PNG and request.headers["content-type"] == "image/png"
            return httpx.Response(201)
        if request.url.path == "/rest/posts":
            body = json.loads(request.content)
            assert body["author"] == "urn:li:person:abc"
            assert body["content"]["media"]["id"] == "urn:li:image:9"
            assert "{hashtag|\\#|AI}" in body["commentary"]
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:123"})
        return httpx.Response(404)

    real_client = httpx.Client
    monkeypatch.setattr(li.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    fetcher = FakeFetcher()
    fetcher.add("https://cdn.example.com/card.png", PNG, "image/png")
    publisher = li.LinkedInPublisher("id", "secret", "http://cb", fetcher=fetcher)
    result = publisher.publish(
        {"platform_user_id": "abc", "access_token": "tok"}, "第一行\n#AI", "https://cdn.example.com/card.png"
    )
    assert result.external_post_id == "urn:li:share:123"
    assert result.permalink == "https://www.linkedin.com/feed/update/urn:li:share:123/"
    assert [m for m, _ in seen] == ["POST", "PUT", "POST"]
    assert fetcher.calls == ["https://cdn.example.com/card.png"]  # downloaded via the SSRF-safe fetcher


def test_linkedin_publish_error_message(monkeypatch):
    def handler(request):
        return httpx.Response(422, json={"message": "Content is a duplicate", "status": 422})

    real_client = httpx.Client
    monkeypatch.setattr(li.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(li.PublishError, match="duplicate"):
        li.LinkedInPublisher("id", "s", "cb").publish({"platform_user_id": "a", "access_token": "t"}, "hi", None)


def test_linkedin_authorize_url_scopes():
    url = li.LinkedInPublisher("cid", "s", "http://127.0.0.1:8000/api/accounts/linkedin/callback").authorize_url("st")
    assert url.startswith(li.AUTH_URL) and "w_member_social" in url and "openid" in url and "state=st" in url


def test_accounts_include_linkedin(client):
    rows = {a["platform"]: a for a in client.get("/api/accounts").json()}
    assert set(rows) == {"threads", "instagram", "linkedin"}
    connect(client, "linkedin")
    assert {a["platform"]: a for a in client.get("/api/accounts").json()}["linkedin"]["connected"]


def test_generation_writes_linkedin_caption(client):
    post = create_post(client)
    assert post["caption_linkedin"] and "#AI" in post["caption_linkedin"]
    assert post["versions"][-1]["caption_linkedin"] == post["caption_linkedin"]


def test_publish_to_linkedin_uses_its_caption(client, services):
    post = to_approved(client, ("linkedin",))
    client.post(f"/api/posts/{post['id']}/publish")
    done = client.get(f"/api/posts/{post['id']}").json()
    assert done["status"] == "published"
    pub = done["publications"][0]
    assert pub["platform"] == "linkedin" and "linkedin.com/feed/update" in pub["permalink"]
    call = services.publishers["linkedin"].calls[0]
    assert call["caption"] == done["caption_linkedin"] and call["image_url"]


def test_submit_blocks_long_linkedin_caption(client):
    connect(client, "linkedin")
    post = create_post(client)
    client.patch(f"/api/posts/{post['id']}", json={"caption_linkedin": "字" * 3001})
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": ["linkedin"]})
    assert resp.status_code == 422 and "LinkedIn" in resp.json()["message"]


def test_sensitive_word_in_linkedin_caption_blocks_publish(client):
    post = to_approved(client, ("linkedin",))
    client.post(f"/api/posts/{post['id']}/reject")
    client.patch(f"/api/posts/{post['id']}", json={"caption_linkedin": "這是未公開產品的消息"})
    export_card(client, post["id"])
    # caught as early as submit now, with the word that matched
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": ["linkedin"]})
    assert resp.status_code == 422 and resp.json()["code"] == "sensitive_content"
    assert resp.json()["detail"]["detected"] == ["未公開產品"]


# ---------------------------------------------------------------- research
def test_research_endpoint_returns_articles_with_pictures(client):
    resp = client.post("/api/research", json={"query": "AI 新創"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["backend"] == "mock" and body["with_images"] == len(body["results"]) == 3
    assert all(r["image_url"].startswith("https://") for r in body["results"])


def test_research_requires_query(client):
    assert client.post("/api/research", json={"query": "   "}).status_code == 422


def test_page_meta_reads_og_tags():
    page = """<html><head>
      <meta content="https://cdn.site.com/a.jpg" property="og:image">
      <meta property='og:site_name' content='聯合新聞網'>
      <meta name="description" content="摘要 &amp; 重點">
    </head></html>"""
    meta = page_meta(page, "https://udn.com/news/1")
    assert meta["image_url"] == "https://cdn.site.com/a.jpg"
    assert meta["source"] == "聯合新聞網" and meta["summary"] == "摘要 & 重點"
    assert page_meta('<meta property="og:image" content="/img/b.png">', "https://x.com/n/1")["image_url"] == "https://x.com/img/b.png"


def test_rss_search_prefers_publisher_picture(services):
    feed = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0" xmlns:News="https://www.bing.com/x"><channel>
      <item><title>新聞一</title>
        <link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fnews.example.com%2fstory%2f1&amp;c=1</link>
        <description>摘要一</description><pubDate>Tue, 17 Nov 2026 12:42:00 GMT</pubDate>
        <News:Source>示範新聞網</News:Source><News:Image>http://www.bing.com/th?id=A&amp;pid=News</News:Image>
        <News:ImageMaxWidth>1107</News:ImageMaxWidth><News:ImageMaxHeight>738</News:ImageMaxHeight></item>
      <item><title>新聞二</title>
        <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fother.example.com%2f2</link>
        <News:Image>http://www.bing.com/th?id=B&amp;pid=News</News:Image></item>
    </channel></rss>"""
    fetcher = services.fetcher
    fetcher.add("https://www.bing.com/news/search?q=AI&format=rss&mkt=zh-TW", feed.encode(), "application/rss+xml")
    fetcher.add(
        "https://news.example.com/story/1",
        b'<meta property="og:image" content="https://news.example.com/lead.jpg">',
        "text/html",
    )
    refs = RssResearch(fetcher).search("AI", 5)
    assert [r.url for r in refs] == ["https://news.example.com/story/1", "https://other.example.com/2"]
    assert refs[0].image_url == "https://news.example.com/lead.jpg"  # publisher's own picture
    assert refs[0].source == "示範新聞網" and refs[0].published == "2026-11-17"
    assert refs[1].image_url == "https://www.bing.com/th?id=B&pid=News&w=1080&h=1080&c=14"  # fallback thumbnail
    assert refs[1].source == "other.example.com"


EMPTY_FEED = b'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>x</title></channel></rss>'
ONE_ITEM_FEED = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
  <item><title>All Code Is Slop (Except Mine)</title>
    <link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fnote.com%2fa%2f1</link></item>
</channel></rss>"""


def _feed(*items: tuple[str, str]) -> bytes:
    rows = "".join(
        f"<item><title>{title}</title><link>http://www.bing.com/news/apiclick.aspx?url={url}</link></item>"
        for title, url in items
    )
    return f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>{rows}</channel></rss>'.encode()


def test_rss_search_covers_zh_and_en_markets_interleaved(services):
    fetcher = services.fetcher
    base = "https://www.bing.com/news/search?q=SpaceX&format=rss&mkt="
    fetcher.add(base + "zh-TW", _feed(("星艦回收", "https://tw.example.com/1"), ("星艦第二則", "https://tw.example.com/2")),
                "application/xml")
    fetcher.add(base + "en-US", _feed(("Starship caught", "https://us.example.com/1"),
                                      ("星艦回收", "https://tw.example.com/1")), "application/xml")  # duplicate
    refs = RssResearch(fetcher, "zh-TW,en-US").search("SpaceX", 5)
    assert [r.url for r in refs] == ["https://tw.example.com/1", "https://us.example.com/1", "https://tw.example.com/2"]


def test_rss_search_finds_english_story_missing_from_zh_market(services):
    fetcher = services.fetcher
    q = "SpaceX%20all%20AI%20code%20are%20slop%20except%20mine"
    fetcher.add(f"https://www.bing.com/news/search?q={q}&format=rss&mkt=zh-TW", EMPTY_FEED, "application/xml")
    fetcher.add(f"https://www.bing.com/news/search?q={q}&format=rss&mkt=en-US", ONE_ITEM_FEED, "application/xml")
    refs = RssResearch(fetcher).search("SpaceX all AI code are slop except mine", 5)
    assert [r.url for r in refs] == ["https://note.com/a/1"]


def test_rss_search_survives_one_market_failing(services):
    fetcher = services.fetcher  # en-US is not registered → HTTP 404 for that market only
    fetcher.add("https://www.bing.com/news/search?q=AI&format=rss&mkt=zh-TW",
                _feed(("新聞", "https://tw.example.com/1")), "application/xml")
    assert [r.url for r in RssResearch(fetcher, "zh-TW,en-US").search("AI", 5)] == ["https://tw.example.com/1"]
    with pytest.raises(Exception, match="新聞搜尋失敗"):
        RssResearch(fetcher, "en-US").search("AI", 5)


def test_parse_markets():
    from app.services.research import parse_markets

    assert parse_markets(" zh-TW , en-US,zh-TW ") == ["zh-TW", "en-US"]
    assert parse_markets("") == ["zh-TW"]


def test_safe_fetcher_does_not_offer_alpn():
    # httpcore calls set_alpn_protocols(["http/1.1"]) on every connection; Bing answers that
    # TLS fingerprint with an empty / off-topic news feed, so the fetcher must ignore it.
    ctx = SafeFetcher()._tls
    ctx.set_alpn_protocols(["http/1.1"])
    assert ctx.verify_mode.name == "CERT_REQUIRED" and ctx.check_hostname


def test_safe_fetcher_refuses_private_addresses():
    fetcher = SafeFetcher(timeout=2)
    for url in ("http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd", "http://10.0.0.5/", "http://[::1]/"):
        with pytest.raises(FetchError):
            fetcher.get(url, 1000)


def test_normalize_picture_crops_square_jpeg():
    from io import BytesIO

    from PIL import Image

    out = normalize_picture(jpeg_bytes(1600, 900))
    with Image.open(BytesIO(out)) as img:
        assert img.size == (1080, 1080) and img.format == "JPEG"
    with pytest.raises(Exception, match="太小"):
        normalize_picture(jpeg_bytes(200, 120))


# ---------------------------------------------------------------- real pictures on the card
def test_photo_mode_uses_news_picture_and_credits_it(client, services):
    services.fetcher.add(PHOTO, jpeg_bytes())
    post = create_post(client, reference=REFERENCE, image_mode="photo")
    assert post["status"] == "editing", post.get("generation_error")
    canvas = post["canvas_json"]
    assert canvas["image_mode"] == "photo" and canvas["credit"] == "圖片來源：示範新聞網"
    assert canvas["reference"]["url"] == REFERENCE["url"]
    sources = [i["source"] for i in post["images"]]
    assert sources == ["reference"] and canvas["image"]["url"] == post["images"][0]["public_url"]
    # the article is linked so readers can check it
    assert REFERENCE["url"] in post["caption_linkedin"] and "示範新聞網" in post["caption_linkedin"]
    assert REFERENCE["url"] in post["caption_threads"] and len(post["caption_threads"]) <= 500


def test_unreachable_picture_falls_back_to_ai_background(client):
    post = create_post(client, reference=REFERENCE, image_mode="photo")  # FakeFetcher → 404
    canvas = post["canvas_json"]
    assert post["status"] == "editing"
    assert canvas["image_mode"] == "ai" and "改用 AI 底圖" in canvas["image_note"]
    assert [i["source"] for i in post["images"]] == ["generated"]


def test_blend_without_image_model_keeps_photo(client, services):
    services.fetcher.add(PHOTO, jpeg_bytes())
    post = create_post(client, reference=REFERENCE, image_mode="blend")
    canvas = post["canvas_json"]
    assert canvas["image_mode"] == "photo" and "FAL_API_KEY" in canvas["image_note"]


def test_blend_with_image_model(client, services):
    class FakeFal:
        def __init__(self):
            self.prompts = []

        def generate(self, prompt):
            return b"\x89PNG\r\n\x1a\nAI"

        def blend(self, prompt, photo):
            self.prompts.append(prompt)
            assert photo.startswith(b"\xff\xd8\xff")
            return b"\x89PNG\r\n\x1a\nBLEND"

    fal = FakeFal()
    services.ai = FluxImageAI(services.ai, fal)
    services.fetcher.add(PHOTO, jpeg_bytes())
    post = create_post(client, reference=REFERENCE, image_mode="blend")
    canvas = post["canvas_json"]
    assert canvas["image_mode"] == "blend" and canvas["credit"].endswith("（AI 融合）")
    assert [i["source"] for i in post["images"]] == ["reference", "generated"]
    assert "news photograph" in fal.prompts[0]


def test_reference_kept_on_regenerate_and_dropped_with_null(client, services):
    services.fetcher.add(PHOTO, jpeg_bytes())
    post = create_post(client, reference=REFERENCE, image_mode="photo")
    client.post(f"/api/posts/{post['id']}/generate", json={"mode": "short"})
    again = client.get(f"/api/posts/{post['id']}").json()
    assert again["canvas_json"]["image_mode"] == "photo" and again["canvas_json"]["reference"]["title"] == REFERENCE["title"]
    client.post(f"/api/posts/{post['id']}/generate", json={"reference": None})
    dropped = client.get(f"/api/posts/{post['id']}").json()
    assert dropped["canvas_json"]["image_mode"] == "ai" and dropped["canvas_json"]["reference"] is None


def test_reference_rejects_non_http_urls(client):
    bad = {**REFERENCE, "image_url": "file:///etc/passwd"}
    body = {"goal": "x", "selected": CANDIDATE, "reference": bad}
    assert client.post("/api/posts", json=body).status_code == 422


def test_resolve_ignores_image_mode_without_reference():
    assert design.resolve(None, None, None, "photo", None)["image_mode"] == "ai"
    ref = Reference.model_validate(REFERENCE).model_dump()
    assert design.resolve(None, None, None, None, ref)["image_mode"] == "photo"
