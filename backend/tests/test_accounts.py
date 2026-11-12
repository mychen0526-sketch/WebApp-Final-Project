from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services.platforms.base import AccountToken, PublishError
from app.services.platforms.instagram import InstagramPublisher
from app.services.platforms.threads import ThreadsPublisher


def test_mock_connect_and_disconnect(client):
    assert all(not a["connected"] for a in client.get("/api/accounts").json())
    resp = client.get("/api/accounts/threads/connect").json()
    assert resp["mock"] is True
    accounts = {a["platform"]: a for a in client.get("/api/accounts").json()}
    assert accounts["threads"]["connected"] and accounts["threads"]["username"] == "demo_threads"
    assert "access_token" not in accounts["threads"]
    assert client.delete("/api/accounts/threads").status_code == 204
    assert not client.get("/api/accounts").json()[0]["connected"]
    assert client.get("/api/accounts/x/connect").status_code == 422


class FakeOAuthPublisher:
    platform = "threads"
    is_mock = False

    def configured(self):
        return True

    def authorize_url(self, state):
        return f"https://threads.net/oauth/authorize?state={state}"

    def exchange_code(self, code):
        return AccountToken("tid", "real_user", f"token-{code}", None)

    def publish(self, *a):  # pragma: no cover
        raise NotImplementedError


def test_oauth_state_roundtrip(client, services):
    services.publishers["threads"] = FakeOAuthPublisher()
    url = client.get("/api/accounts/threads/connect").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]

    resp = client.get(f"/api/accounts/threads/callback?code=abc&state={state}", follow_redirects=False)
    assert resp.status_code == 302 and "connected=threads" in resp.headers["location"]
    assert services.repo.get_account("11111111-1111-1111-1111-111111111111", "threads")["access_token"] == "token-abc"

    tampered = client.get(f"/api/accounts/threads/callback?code=abc&state={state}x", follow_redirects=False)
    assert "connect_error" in tampered.headers["location"]
    # state for threads cannot be replayed on instagram
    services.publishers["instagram"] = FakeOAuthPublisher()
    cross = client.get(f"/api/accounts/instagram/callback?code=abc&state={state}", follow_redirects=False)
    assert "connect_error" in cross.headers["location"]


def test_connect_unconfigured_platform_is_503(client, services):
    services.publishers["instagram"] = InstagramPublisher("", "", "http://x/cb")
    assert client.get("/api/accounts/instagram/connect").status_code == 503


# ---------------------------------------------------------------- real publishers against a fake Graph API
def _transport(handler):
    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    return factory


def test_threads_publish_two_step_flow(monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/threads"):
            return httpx.Response(200, json={"id": "c1"})
        if path.endswith("/c1"):
            status = "IN_PROGRESS" if sum(p == path for _, p in seen) == 1 else "FINISHED"
            return httpx.Response(200, json={"status": status})
        if path.endswith("/threads_publish"):
            return httpx.Response(200, json={"id": "m1"})
        if path.endswith("/m1"):
            return httpx.Response(200, json={"permalink": "https://threads.net/p/m1"})
        return httpx.Response(404)

    monkeypatch.setattr("app.services.platforms.threads.httpx.Client", _transport(handler))
    pub = ThreadsPublisher("id", "secret", "cb", poll_attempts=3, poll_interval=0)
    result = pub.publish({"platform_user_id": "u1", "access_token": "t"}, "hello", "https://img/x.png")
    assert result.external_post_id == "m1" and result.permalink == "https://threads.net/p/m1"
    assert [p for _, p in seen].count("/v1.0/c1") == 2  # waited for FINISHED


def test_instagram_requires_image_and_reports_graph_errors(monkeypatch):
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "Application request limit reached"}})

    monkeypatch.setattr("app.services.platforms.instagram.httpx.Client", _transport(handler))
    pub = InstagramPublisher("id", "secret", "cb", poll_attempts=1, poll_interval=0)
    with pytest.raises(PublishError, match="一定要有圖片"):
        pub.publish({"platform_user_id": "u", "access_token": "t"}, "cap", None)
    with pytest.raises(PublishError, match="limit"):
        pub.publish({"platform_user_id": "u", "access_token": "t"}, "cap", "https://img/x.png")


def test_container_error_status(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "c9"})
        return httpx.Response(200, json={"status_code": "ERROR", "error_message": "bad image"})

    monkeypatch.setattr("app.services.platforms.instagram.httpx.Client", _transport(handler))
    pub = InstagramPublisher("id", "secret", "cb", poll_attempts=2, poll_interval=0)
    with pytest.raises(PublishError, match="bad image"):
        pub.publish({"platform_user_id": "u", "access_token": "t"}, "cap", "https://img/x.png")
