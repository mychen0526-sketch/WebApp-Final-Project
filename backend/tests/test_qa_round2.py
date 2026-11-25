"""Regression tests for 第一輪測試Ⅱ (BUG-07～22), QA/QC 補測 (QA-N01～N03) and the external review
(token storage, expired / revoked authorization, single-platform failure and retry)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.main import InsecureConfig, create_app
from app.services import safety
from app.services.platforms.mock import MockPublisher
from app.services.progress import ProgressHub
from app.services.scheduler import run_due_once

from .conftest import USER, connect, create_post, export_card, submit, to_approved, to_pending

HTML_AS_PNG = ("x.png", b"<html><script>alert(1)</script></html>", "image/png")


def _pub(client, post_id, platform):
    post = client.get(f"/api/posts/{post_id}").json()
    return post, next(p for p in post["publications"] if p["platform"] == platform)


# ---------------------------------------------------------------- BUG-07 normalized matching
@pytest.mark.parametrize("text", ["SECRET", "secret", "Ｓｅｃｒｅｔ", "Sec ret", "機密 客戶", "機密　客戶", "機密​客戶", "ｓｅｃｒｅｔ!"])
def test_bug07_sensitive_words_match_case_width_and_spacing(client, text):
    client.put("/api/settings", json={"sensitive_words": ["Secret", "機密客戶"]})
    result = client.post("/api/safety/scan", json={"text": text}).json()
    assert result["ok"] is False and result["detected"], text


def test_bug07_normalize_keeps_ordinary_text_apart():
    assert safety.scan("公開產品發表會", ["未公開產品"])["ok"] is True
    assert safety.scan("Secretary", ["secret"])["detected"] == ["secret"]  # substring, as before


# ---------------------------------------------------------------- BUG-09 scheduled / retried posts are re-scanned
def test_bug09_word_added_after_scheduling_stops_scheduled_publish(client, services):
    post = to_approved(client)
    future = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    assert client.post(f"/api/posts/{post['id']}/schedule", json={"when": future}).status_code == 200
    client.put("/api/settings", json={"sensitive_words": ["新創"]})
    services.repo.posts[post["id"]]["scheduled_at"] = "2020-01-01T00:00:00+00:00"
    run_due_once(services)
    done, threads = _pub(client, post["id"], "threads")
    assert done["status"] == "publish_failed"
    assert threads["error_code"] == "sensitive" and "新創" in threads["error_message"]
    assert services.publishers["threads"].calls == []  # nothing went out
    # retry is refused with the word until the post is edited
    resp = client.post(f"/api/posts/{post['id']}/retry")
    assert resp.status_code == 422 and resp.json()["detail"]["detected"] == ["新創"]


# ---------------------------------------------------------------- BUG-11 scan what is shown, and at submit
def test_bug11_hidden_description_does_not_block_but_visible_words_block_at_submit(client):
    connect(client, "threads")
    post = create_post(client)
    canvas = post["canvas_json"]
    for t in canvas["texts"]:
        if t["textType"] == "description":
            t["text"] = "機密客戶的名字"
    client.patch(f"/api/posts/{post['id']}", json={"canvas_json": canvas})
    assert submit(client, post["id"], ["threads"]).status_code == 200  # description is not drawn on the card

    other = create_post(client)
    client.patch(f"/api/posts/{other['id']}", json={"caption_threads": "跟機密客戶的合作"})
    resp = submit(client, other["id"], ["threads"])
    assert resp.status_code == 422 and resp.json()["detail"]["detected"] == ["機密客戶"]


def test_bug11_approve_rescans(client):
    post = to_pending(client)
    client.put("/api/settings", json={"sensitive_words": ["新創"]})
    resp = client.post(f"/api/posts/{post['id']}/approve", json={"readConfirmed": True, "rightsConfirmed": True})
    assert resp.status_code == 422 and resp.json()["code"] == "sensitive_content"


# ---------------------------------------------------------------- BUG-13 settings that survive a reload
def test_bug13_default_platforms_and_recent_feedback_persist(client, other):
    assert client.get("/api/settings").json()["default_platforms"] == []
    resp = client.put("/api/settings", json={"default_platforms": ["threads", "linkedin", "threads"]})
    assert resp.json()["default_platforms"] == ["threads", "linkedin"]
    assert client.get("/api/settings").json()["default_platforms"] == ["threads", "linkedin"]
    assert client.put("/api/settings", json={"default_platforms": ["x"]}).status_code == 422

    post = create_post(client)
    client.post(f"/api/posts/{post['id']}/feedback", json={"rating": "like"})
    client.post(f"/api/posts/{post['id']}/feedback", json={"rating": "dislike"})
    rows = client.get("/api/feedback").json()
    assert [r["rating"] for r in rows] == ["dislike", "like"] and rows[0]["post_title"] == post["title"]
    assert other.get("/api/feedback").json() == []


# ---------------------------------------------------------------- BUG-15 deleted template
def test_bug15_deleted_template_falls_back_on_regenerate_too(client, services):
    from .test_templates import upload

    tpl = upload(client)
    post = create_post(client, template_id=tpl["id"])
    client.delete(f"/api/templates/{tpl['id']}")
    resp = client.post(f"/api/posts/{post['id']}/generate", json={"template_id": tpl["id"]})
    assert resp.status_code == 202 and resp.json()["notices"] == ["這張模板已經刪除，改用 AI 底圖"]
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "editing"


# ---------------------------------------------------------------- BUG-17 no picture swap after review
def test_bug17_cannot_upload_after_submit_or_approval(client):
    post = to_approved(client)
    resp = client.post(f"/api/posts/{post['id']}/images", files={"file": ("a.png", b"\x89PNG\r\n\x1a\nx", "image/png")}, data={"source": "exported"})
    assert resp.status_code == 409
    after = client.get(f"/api/posts/{post['id']}").json()
    assert after["status"] == "approved" and len([i for i in after["images"] if i["source"] == "exported"]) == 1


# ---------------------------------------------------------------- BUG-20 canvas_json cannot smuggle URLs / paths
def test_bug20_canvas_template_and_image_url_are_not_trusted(client, services):
    post = create_post(client)
    canvas = {
        **post["canvas_json"],
        "template_id": "x",
        "image": {"url": "http://169.254.169.254/latest/meta-data/"},
        "template_path": "../../someone-else/x.png",
    }
    client.patch(f"/api/posts/{post['id']}", json={"canvas_json": canvas})
    resp = client.post(f"/api/posts/{post['id']}/generate", json={})
    assert resp.status_code == 202
    after = client.get(f"/api/posts/{post['id']}").json()
    assert all("169.254" not in i["public_url"] and ".." not in i["storage_path"] for i in after["images"])
    assert after["images"][-1]["source"] == "generated"


def test_bug20_canvas_size_is_capped(client):
    post = create_post(client)
    huge = {"texts": [], "junk": "x" * 70_000}
    assert client.patch(f"/api/posts/{post['id']}", json={"canvas_json": huge}).status_code == 422


# ---------------------------------------------------------------- BUG-21 refuse to run with the template secret
@pytest.mark.parametrize("secret", ["change-me-in-env", "change-me-to-a-long-random-string", "short"])
def test_bug21_live_publishing_refuses_weak_app_secret(secret):
    settings = Settings(_env_file=None, mock_publish=False, scheduler_enabled=False, app_secret=secret)
    with pytest.raises(InsecureConfig):
        create_app(app_settings=settings)


def test_bug21_mock_mode_still_starts_with_template_secret():
    settings = Settings(_env_file=None, mock_publish=True, mock_ai=True, scheduler_enabled=False, app_secret="change-me-in-env")
    assert create_app(app_settings=settings)


# ---------------------------------------------------------------- BUG-22 file type from content
def test_bug22_fake_png_rejected_for_templates_and_posts(client):
    assert client.post("/api/templates", files={"file": HTML_AS_PNG}).status_code == 422
    post = create_post(client)
    assert client.post(f"/api/posts/{post['id']}/images", files={"file": HTML_AS_PNG}).status_code == 422
    # a real JPEG labelled as PNG is accepted and stored as JPEG
    from .conftest import jpeg_bytes

    ok = client.post("/api/templates", files={"file": ("a.png", jpeg_bytes(10, 10), "image/png")})
    assert ok.status_code == 201 and ok.json()["storage_path"].endswith(".jpg")


def test_bug22_oversized_upload_rejected(client):
    big = b"\x89PNG\r\n\x1a\n" + b"\0" * (8 * 1024 * 1024 + 1)
    assert client.post("/api/templates", files={"file": ("big.png", big, "image/png")}).status_code == 422


# ---------------------------------------------------------------- QA-N01 no submit without a fresh card export
def test_qa_n01_submit_needs_fresh_exported_card(client):
    connect(client, "threads")
    post = create_post(client)
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": ["threads"]})
    assert resp.status_code == 422 and "匯出" in resp.json()["message"]
    export_card(client, post["id"])
    client.patch(f"/api/posts/{post['id']}", json={"title": "改過的標題"})  # edited after the export
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": ["threads"]})
    assert resp.status_code == 422 and "重新匯出" in resp.json()["message"]
    assert submit(client, post["id"], ["threads"]).status_code == 200


# ---------------------------------------------------------------- QA-N02 lost response must not double-post
def test_qa_n02_lost_response_then_retry_finds_post_instead_of_posting_twice(client, services):
    post = to_approved(client, ("threads",))
    threads = services.publishers["threads"]
    threads.lose_response = True
    client.post(f"/api/posts/{post['id']}/publish")
    done, pub = _pub(client, post["id"], "threads")
    assert done["status"] == "publish_failed" and pub["error_code"] == "uncertain"
    assert len(threads.remote) == 1  # it did go live

    assert client.post(f"/api/posts/{post['id']}/retry").status_code == 202
    final, pub = _pub(client, post["id"], "threads")
    assert final["status"] == "published" and pub["status"] == "success"
    assert len(threads.remote) == 1 and len(threads.calls) == 1  # found it, did not post again
    assert pub["external_post_id"] == threads.remote[0]["result"].external_post_id


def test_qa_n02_uncertain_and_really_missing_posts_again(client, services):
    post = to_approved(client, ("threads",))
    threads = services.publishers["threads"]
    threads.lose_response = True
    client.post(f"/api/posts/{post['id']}/publish")
    threads.remote.clear()  # it did not go live after all
    client.post(f"/api/posts/{post['id']}/retry")
    final, _ = _pub(client, post["id"], "threads")
    assert final["status"] == "published" and len(threads.calls) == 2


def test_qa_n02_unsearchable_platform_needs_user_confirmation(client, services):
    post = to_approved(client, ("linkedin",))
    linkedin = services.publishers["linkedin"]
    linkedin.supports_lookup = False
    linkedin.lose_response = True
    client.post(f"/api/posts/{post['id']}/publish")
    resp = client.post(f"/api/posts/{post['id']}/retry")
    assert resp.status_code == 409 and resp.json()["code"] == "publish_uncertain"
    assert resp.json()["detail"]["platforms"] == ["linkedin"]
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "publish_failed"
    ok = client.post(f"/api/posts/{post['id']}/retry", json={"confirm_unpublished": ["linkedin"]})
    assert ok.status_code == 202
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "published"


# ---------------------------------------------------------------- QA-N03 never stuck in publishing
def test_qa_n03_failure_before_platform_loop_ends_in_publish_failed(client, services, monkeypatch):
    post = to_approved(client, ("threads",))

    real = services.repo.list_images
    calls = []

    def broken(post_id):  # the response itself reads images first; break the background publish
        calls.append(post_id)
        if len(calls) == 2:
            raise RuntimeError("storage down")
        return real(post_id)

    monkeypatch.setattr(services.repo, "list_images", broken)
    client.post(f"/api/posts/{post['id']}/publish")
    monkeypatch.undo()
    done, pub = _pub(client, post["id"], "threads")
    assert done["status"] == "publish_failed" and pub["error_code"] == "internal"
    assert client.post(f"/api/posts/{post['id']}/retry").status_code == 202
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "published"


def test_qa_n03_scheduler_recovers_posts_stuck_in_publishing(client, services):
    post = to_approved(client, ("threads", "instagram"))
    repo = services.repo
    repo.update_post(USER, post["id"], {"status": "publishing"})
    repo.upsert_publication(post["id"], "threads", {"status": "success", "external_post_id": "t1"})
    repo.upsert_publication(post["id"], "instagram", {"status": "pending"})
    repo.posts[post["id"]]["updated_at"] = "2020-01-01T00:00:00+00:00"
    run_due_once(services)
    done, ig = _pub(client, post["id"], "instagram")
    assert done["status"] == "partially_published"
    assert ig["status"] == "failed" and ig["error_code"] == "uncertain"


# ---------------------------------------------------------------- single-platform failures
def test_transient_error_is_retried_automatically(client, services):
    post = to_approved(client, ("threads",))
    threads = services.publishers["threads"]
    threads.fail_with, threads.fail_kind, threads.fail_times = "HTTP 503", "transient", 2
    client.post(f"/api/posts/{post['id']}/publish")
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "published"
    assert len(threads.calls) == 3


def test_one_platform_failing_keeps_others_and_reports_kind(client, services):
    post = to_approved(client, ("threads", "instagram"))
    services.publishers["instagram"].fail_with = "Application request limit reached"
    client.post(f"/api/posts/{post['id']}/publish")
    done, ig = _pub(client, post["id"], "instagram")
    assert done["status"] == "partially_published"
    assert ig["error_code"] == "rejected" and "limit" in ig["error_message"]


# ---------------------------------------------------------------- tokens: storage, expiry, revocation
def test_tokens_encrypted_at_rest_and_decrypted_for_publishing(client, services):
    post = to_approved(client, ("threads",))
    stored = services.repo.get_account(USER, "threads")["access_token"]
    assert stored.startswith("enc:v1:") and "mock-token" not in stored
    client.post(f"/api/posts/{post['id']}/publish")
    assert services.publishers["threads"].calls[0]["token"].startswith("mock-token-")


def test_legacy_plaintext_token_still_works(client, services):
    post = to_approved(client, ("threads",))
    services.repo.update_account(USER, "threads", {"access_token": "plain-old-token"})
    client.post(f"/api/posts/{post['id']}/publish")
    assert services.publishers["threads"].calls[0]["token"] == "plain-old-token"


def test_revoked_token_flags_account_until_reconnect(client, services):
    post = to_approved(client, ("threads",))
    threads = services.publishers["threads"]
    threads.fail_with, threads.fail_kind = "Error validating access token: The user has not authorized application", "auth"
    client.post(f"/api/posts/{post['id']}/publish")
    _, pub = _pub(client, post["id"], "threads")
    assert pub["error_code"] == "auth"
    account = next(a for a in client.get("/api/accounts").json() if a["platform"] == "threads")
    assert account["needs_reconnect"] and account["expired"] and account["auth_error"]

    # other posts cannot be submitted to it either, with a clear reason
    draft = create_post(client)
    resp = submit(client, draft["id"], ["threads"])
    assert resp.status_code == 422 and "重新連結" in resp.json()["message"]

    threads.fail_with = None
    connect(client, "threads")  # reconnect clears the flag
    account = next(a for a in client.get("/api/accounts").json() if a["platform"] == "threads")
    assert not account["needs_reconnect"]
    assert client.post(f"/api/posts/{post['id']}/retry").status_code == 202
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "published"


def test_expired_token_fails_platform_with_auth_code(client, services):
    post = to_approved(client, ("threads",))
    services.repo.update_account(USER, "threads", {"token_expires_at": "2020-01-01T00:00:00+00:00"})
    client.post(f"/api/posts/{post['id']}/publish")
    _, pub = _pub(client, post["id"], "threads")
    assert pub["error_code"] == "auth" and "過期" in pub["error_message"]


class NoRefreshPublisher(MockPublisher):
    refresh = property(lambda self: (_ for _ in ()).throw(AttributeError("refresh")))


def test_tokens_close_to_expiry_are_refreshed(client, services):
    connect(client, "threads", "linkedin")
    soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    for platform in ("threads", "linkedin"):
        services.repo.update_account(USER, platform, {"token_expires_at": soon})
    old = services.repo.get_account(USER, "threads")["access_token"]
    services.publishers["linkedin"] = NoRefreshPublisher("linkedin")  # real LinkedIn tokens cannot be refreshed
    run_due_once(services, force_token_refresh=True)
    threads = services.repo.get_account(USER, "threads")
    assert threads["access_token"] != old and threads["access_token"].startswith("enc:v1:")
    assert threads["token_expires_at"] > soon
    accounts = {a["platform"]: a for a in client.get("/api/accounts").json()}
    assert accounts["linkedin"]["expiring_soon"] and not accounts["threads"]["expiring_soon"]


def test_disconnect_revokes_token_at_platform(client, services):
    connect(client, "linkedin")
    token = services.tokens.open(services.repo.get_account(USER, "linkedin")["access_token"])
    assert client.delete("/api/accounts/linkedin").status_code == 204
    assert services.publishers["linkedin"].revoked == [token]
    assert services.repo.get_account(USER, "linkedin") is None


# ---------------------------------------------------------------- 決定-01 (partial): manual edits kept as a version
def test_rewrite_keeps_hand_edited_copy_as_a_version(client):
    post = create_post(client)
    client.patch(f"/api/posts/{post['id']}", json={"caption_threads": "我自己加的新資訊"})
    client.post(f"/api/posts/{post['id']}/generate", json={"mode": "short"})
    versions = client.get(f"/api/posts/{post['id']}").json()["versions"]
    assert [v["mode"] for v in versions] == [None, "manual", "short"]
    assert versions[1]["caption_threads"] == "我自己加的新資訊"


# ---------------------------------------------------------------- ProgressHub does not grow forever
def test_progress_hub_drops_old_finished_runs(monkeypatch):
    hub = ProgressHub()
    token = hub.start("a")
    hub.finish("a", token)
    import app.services.progress as progress

    monkeypatch.setattr(progress, "KEEP_FINISHED_SECONDS", -1)
    hub.start("b")
    assert hub.get("a") is None and len(hub) == 1


# ---------------------------------------------------------------- real publishers classify failures
def _threads_with(monkeypatch, handler):
    import httpx

    from app.services.platforms.threads import ThreadsPublisher

    real = httpx.Client
    monkeypatch.setattr(
        "app.services.platforms.threads.httpx.Client", lambda *a, **kw: real(*a, transport=httpx.MockTransport(handler), **kw)
    )
    return ThreadsPublisher("id", "secret", "cb", poll_attempts=1, poll_interval=0)


def test_threads_timeout_on_final_publish_is_uncertain(monkeypatch):
    import httpx

    from app.services.platforms.base import PublishError

    def handler(request):
        if request.url.path.endswith("/threads"):
            return httpx.Response(200, json={"id": "c1"})
        if request.url.path.endswith("/c1"):
            return httpx.Response(200, json={"status": "FINISHED"})
        raise httpx.ReadTimeout("slow", request=request)

    pub = _threads_with(monkeypatch, handler)
    with pytest.raises(PublishError) as info:
        pub.publish({"platform_user_id": "u", "access_token": "t"}, "hi", None)
    assert info.value.kind == "uncertain"


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (400, {"error": {"message": "Error validating access token", "type": "OAuthException", "code": 190}}, "auth"),
        (503, {"error": {"message": "Service unavailable"}}, "transient"),
        (429, {"error": {"message": "Too many calls"}}, "transient"),
        (400, {"error": {"message": "Param text is too long"}}, "rejected"),
    ],
)
def test_threads_container_errors_are_classified(monkeypatch, status, body, kind):
    import httpx

    from app.services.platforms.base import PublishError

    pub = _threads_with(monkeypatch, lambda request: httpx.Response(status, json=body))
    with pytest.raises(PublishError) as info:
        pub.publish({"platform_user_id": "u", "access_token": "t"}, "hi", None)
    assert info.value.kind == kind


def test_linkedin_401_is_auth_and_refuses_internal_image(monkeypatch):
    import httpx

    from app.services.platforms import linkedin as li
    from app.services.platforms.base import PublishError
    from app.services.webfetch import SafeFetcher

    real = httpx.Client
    monkeypatch.setattr(li.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Revoked"})), **kw))
    pub = li.LinkedInPublisher("id", "s", "cb", fetcher=SafeFetcher())
    with pytest.raises(PublishError) as info:
        pub.publish({"platform_user_id": "a", "access_token": "t"}, "hi", None)
    assert info.value.kind == "auth"
    with pytest.raises(PublishError, match="讀不到要發布的圖片"):
        pub.publish({"platform_user_id": "a", "access_token": "t"}, "hi", "http://169.254.169.254/latest/meta-data/")
