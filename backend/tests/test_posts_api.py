import time

import jwt

from .conftest import CANDIDATE, JWT_SECRET, USER, connect, create_post, to_approved, to_pending


def test_candidates_returns_three(client):
    resp = client.post("/api/candidates", json={"goal": "OpenAI 新公告", "tone": "專業分析"})
    assert resp.status_code == 200
    cands = resp.json()["candidates"]
    assert len(cands) == 3 and all({"title", "angle", "hook"} <= set(c) for c in cands)


def test_blank_goal_rejected(client):
    assert client.post("/api/candidates", json={"goal": "   "}).status_code == 422


def test_create_generates_draft(client):
    post = create_post(client, layout="bottom", style=2)
    assert post["status"] == "editing"
    assert post["caption_threads"] and post["caption_instagram"]
    canvas = post["canvas_json"]
    assert canvas["layout"] == "bottom" and canvas["style"] == 2
    assert [t["textType"] for t in canvas["texts"]] == ["headline", "highlight", "description"]
    assert canvas["texts"][0]["position"] == {"x": 540, "y": 760}
    assert len(post["images"]) == 1 and post["images"][0]["source"] == "generated"
    # generated image is served in memory mode
    assert client.get(post["images"][0]["public_url"].replace("http://testserver", "")).status_code == 200


def test_generation_failure_lands_in_generation_failed_then_retry(client, services):
    services.ai.fail_next = True
    post = create_post(client)
    assert post["status"] == "generation_failed" and post["generation_error"]
    resp = client.post(f"/api/posts/{post['id']}/generate", json={})
    assert resp.status_code == 202
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "editing"


def test_regenerate_with_new_direction(client):
    post = create_post(client)
    new = {"title": "觀點與預測", "angle": "推演半年後的走向", "hook": "我的預測不太一樣"}
    client.post(f"/api/posts/{post['id']}/generate", json={"selected": new, "mode": "short"})
    again = client.get(f"/api/posts/{post['id']}").json()
    assert again["selected_prompt"]["title"] == "觀點與預測"
    assert again["canvas_json"]["layout"] == post["canvas_json"]["layout"]  # keeps previous design


def test_list_and_filter(client):
    create_post(client)
    to_pending(client)
    assert len(client.get("/api/posts").json()) == 2
    assert [p["status"] for p in client.get("/api/posts?status=pending_review").json()] == ["pending_review"]
    assert client.get("/api/posts?status=nope").status_code == 422


def test_patch_only_in_editing_and_approved(client):
    post = create_post(client)
    resp = client.patch(f"/api/posts/{post['id']}", json={"caption_threads": "改過的文案"})
    assert resp.status_code == 200 and resp.json()["caption_threads"] == "改過的文案"
    assert client.patch(f"/api/posts/{post['id']}", json={"status": "approved"}).status_code == 422  # can't set status

    pending = to_pending(client)
    assert client.patch(f"/api/posts/{pending['id']}", json={"title": "x"}).status_code == 409


def test_patch_after_approve_requires_new_review(client):
    post = to_approved(client)
    resp = client.patch(f"/api/posts/{post['id']}", json={"title": "核准後又改"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "editing" and resp.json()["approved_at"] is None
    assert client.post(f"/api/posts/{post['id']}/publish").status_code == 409


def test_delete_only_drafts(client):
    post = create_post(client)
    pending = to_pending(client)
    assert client.delete(f"/api/posts/{pending['id']}").status_code == 409
    assert client.delete(f"/api/posts/{post['id']}").status_code == 204
    assert client.get(f"/api/posts/{post['id']}").status_code == 404


def test_submit_requires_bound_accounts(client):
    post = create_post(client)
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": ["threads"]})
    assert resp.status_code == 422 and resp.json()["code"] == "submit_blocked"
    assert client.post(f"/api/posts/{post['id']}/submit", json={"platforms": []}).status_code == 422


def test_submit_rejects_expired_account(client, services):
    post = create_post(client)
    services.repo.upsert_account(USER, "threads", {"platform_user_id": "1", "username": "x", "access_token": "t",
                                                   "token_expires_at": "2020-01-01T00:00:00+00:00"})
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": ["threads"]})
    assert resp.status_code == 422 and "過期" in resp.json()["message"]
    assert client.get("/api/accounts").json()[0]["expired"] is True


def test_submit_rejects_long_threads_caption(client):
    connect(client, "threads")
    post = create_post(client)
    client.patch(f"/api/posts/{post['id']}", json={"caption_threads": "字" * 501})
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": ["threads"]})
    assert resp.status_code == 422 and "500" in resp.json()["message"]


def test_approve_needs_both_confirmations(client):
    post = to_pending(client)
    url = f"/api/posts/{post['id']}/approve"
    assert client.post(url, json={"readConfirmed": True}).status_code == 422
    assert client.post(url, json={"read_confirmed": True, "rights_confirmed": True}).status_code == 200
    assert client.post(url, json={"readConfirmed": True, "rightsConfirmed": True}).status_code == 409  # only once


def test_reject_from_pending_and_approved(client):
    pending = to_pending(client)
    assert client.post(f"/api/posts/{pending['id']}/reject").json()["status"] == "editing"
    approved = to_approved(client)
    assert client.post(f"/api/posts/{approved['id']}/return").json()["status"] == "editing"  # README alias


def test_other_users_post_is_invisible(client, other):
    post = create_post(client)
    assert other.get(f"/api/posts/{post['id']}").status_code == 404
    assert other.patch(f"/api/posts/{post['id']}", json={"title": "x"}).status_code == 404
    assert other.get("/api/posts").json() == []


def test_upload_rules(client):
    post = create_post(client)
    png = b"\x89PNG\r\n\x1a\nfake"
    up = client.post(f"/api/posts/{post['id']}/images", files={"file": ("a.png", png, "image/png")}, data={"source": "uploaded"})
    assert up.status_code == 201 and up.json()["source"] == "uploaded"
    bad = client.post(f"/api/posts/{post['id']}/images", files={"file": ("a.gif", b"GIF", "image/gif")})
    assert bad.status_code == 422

    pending = to_pending(client)
    url = f"/api/posts/{pending['id']}/images"
    assert client.post(url, files={"file": ("a.png", png, "image/png")}, data={"source": "uploaded"}).status_code == 409
    # the card that will be published is locked once submitted (BUG-17)
    assert client.post(url, files={"file": ("a.png", png, "image/png")}, data={"source": "exported"}).status_code == 409


def test_feedback(client, services):
    post = create_post(client)
    assert client.post(f"/api/posts/{post['id']}/feedback", json={"rating": "like"}).status_code == 201
    assert client.post(f"/api/posts/{post['id']}/feedback", json={"rating": "meh"}).status_code == 422
    assert services.repo.feedback[0]["rating"] == "like"


def test_settings_roundtrip(client):
    assert client.get("/api/settings").json()["sensitive_words"] == ["未公開產品", "內部代號", "機密客戶"]
    resp = client.put("/api/settings", json={"brand_name": "ORBIT / LAB", "sensitive_words": [" 代號A ", "代號A", ""]})
    assert resp.status_code == 200
    assert resp.json()["brand_name"] == "ORBIT / LAB" and resp.json()["sensitive_words"] == ["代號A"]


def test_auth_required_and_jwt_verified(services):
    from fastapi.testclient import TestClient

    from app.main import create_app

    c = TestClient(create_app(services))
    assert c.get("/api/posts").status_code == 401
    token = jwt.encode({"sub": USER, "aud": "authenticated", "exp": int(time.time()) + 60}, JWT_SECRET, algorithm="HS256")
    assert c.get("/api/posts", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    bad = jwt.encode({"sub": USER, "aud": "authenticated"}, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
    assert c.get("/api/posts", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_dev_header_ignored_when_supabase_configured(services):
    from fastapi.testclient import TestClient

    from app.main import create_app

    services.settings.supabase_url = "https://example.supabase.co"
    services.settings.supabase_service_role_key = "key"
    c = TestClient(create_app(services))
    assert c.get("/api/posts", headers={"X-Dev-User": USER}).status_code == 401


def test_create_requires_selected_candidate(client):
    assert client.post("/api/posts", json={"goal": "x"}).status_code == 422
    assert client.post("/api/posts", json={"goal": "x", "selected": CANDIDATE, "style": 9}).status_code == 422
