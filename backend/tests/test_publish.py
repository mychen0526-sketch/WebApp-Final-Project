from datetime import datetime, timedelta, timezone

from app.services.scheduler import run_due_once
from app.state import Status

from .conftest import create_post, to_approved


def test_publish_success_all_platforms(client, services):
    post = to_approved(client)
    resp = client.post(f"/api/posts/{post['id']}/publish")
    assert resp.status_code == 202 and resp.json()["status"] == "publishing"
    done = client.get(f"/api/posts/{post['id']}").json()
    assert done["status"] == "published"
    assert {p["platform"]: p["status"] for p in done["publications"]} == {"threads": "success", "instagram": "success"}
    assert all(p["permalink"] for p in done["publications"])
    # IG got the generated image; each platform got its own caption
    ig_call = services.publishers["instagram"].calls[0]
    assert ig_call["image_url"] and "#" in ig_call["caption"]


def test_publish_requires_approved(client):
    post = create_post(client)
    resp = client.post(f"/api/posts/{post['id']}/publish")
    assert resp.status_code == 409 and resp.json()["code"] == "invalid_state"


def test_double_publish_rejected(client, services):
    post = to_approved(client)
    # simulate the first click having claimed the post but not finished yet
    services.repo.update_post(post["user_id"], post["id"], {"status": "publishing"})
    assert client.post(f"/api/posts/{post['id']}/publish").status_code == 409


def test_compare_and_set_blocks_second_claim(services, client):
    post = to_approved(client)
    repo = services.repo
    first = repo.update_post(post["user_id"], post["id"], {"status": "publishing"}, expected={Status.APPROVED})
    second = repo.update_post(post["user_id"], post["id"], {"status": "publishing"}, expected={Status.APPROVED})
    assert first is not None and second is None


def test_partial_failure_then_retry_only_failed(client, services):
    post = to_approved(client)
    services.publishers["instagram"].fail_with = "Application request limit reached"
    client.post(f"/api/posts/{post['id']}/publish")
    after = client.get(f"/api/posts/{post['id']}").json()
    assert after["status"] == "partially_published"
    ig = next(p for p in after["publications"] if p["platform"] == "instagram")
    assert ig["status"] == "failed" and "limit" in ig["error_message"]

    services.publishers["instagram"].fail_with = None
    threads_calls = len(services.publishers["threads"].calls)
    assert client.post(f"/api/posts/{post['id']}/retry").status_code == 202
    final = client.get(f"/api/posts/{post['id']}").json()
    assert final["status"] == "published"
    assert len(services.publishers["threads"].calls) == threads_calls  # Threads not posted twice


def test_all_failed_then_reopen_for_editing(client, services):
    post = to_approved(client, platforms=("threads",))
    services.publishers["threads"].fail_with = "boom"
    client.post(f"/api/posts/{post['id']}/publish")
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "publish_failed"
    resp = client.post(f"/api/posts/{post['id']}/reopen")
    assert resp.status_code == 200 and resp.json()["status"] == "editing"


def test_sensitive_word_blocks_publish_and_schedule(client):
    post = to_approved(client)
    client.put("/api/settings", json={"sensitive_words": ["新創"]})
    resp = client.post(f"/api/posts/{post['id']}/publish")
    assert resp.status_code == 422 and resp.json()["code"] == "sensitive_content"
    assert "新創" in resp.json()["detail"]["detected"]
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert client.post(f"/api/posts/{post['id']}/schedule", json={"when": future}).status_code == 422
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "approved"


def test_safety_scan_endpoint(client):
    resp = client.post("/api/safety/scan", json={"title": "內部代號曝光", "text": "保證賺錢"}).json()
    assert resp["ok"] is False and resp["detected"] == ["內部代號"] and resp["claims"] == ["保證賺錢"]


def test_schedule_validation_and_cancel(client):
    post = to_approved(client)
    url = f"/api/posts/{post['id']}"
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert client.post(f"{url}/schedule", json={"when": past}).status_code == 422
    assert client.post(f"{url}/schedule", json={"when": "2030-01-01T09:00:00"}).status_code == 422  # needs timezone
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    scheduled = client.post(f"{url}/schedule", json={"when": future}).json()
    assert scheduled["status"] == "scheduled" and scheduled["scheduled_at"]
    assert [p["id"] for p in client.get("/api/posts?status=scheduled").json()] == [post["id"]]
    assert client.patch(url, json={"title": "x"}).status_code == 409
    assert client.delete(url).status_code == 409
    cancelled = client.post(f"{url}/cancel-schedule").json()
    assert cancelled["status"] == "approved" and cancelled["scheduled_at"] is None


def test_scheduler_publishes_due_posts(client, services):
    post = to_approved(client)
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    client.post(f"/api/posts/{post['id']}/schedule", json={"when": future})
    assert run_due_once(services) == 0
    # move it into the past
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    services.repo.update_post(post["user_id"], post["id"], {"scheduled_at": past})
    assert run_due_once(services) == 1
    assert client.get(f"/api/posts/{post['id']}").json()["status"] == "published"
    assert run_due_once(services) == 0


def test_scheduler_fails_stuck_generation(client, services):
    post = create_post(client)
    services.repo.posts[post["id"]].update(status="generating", updated_at="2020-01-01T00:00:00+00:00")
    run_due_once(services)
    stuck = client.get(f"/api/posts/{post['id']}").json()
    assert stuck["status"] == "generation_failed"


def test_exported_image_preferred_for_publishing(client, services):
    post = to_approved(client, platforms=("instagram",))
    up = client.post(
        f"/api/posts/{post['id']}/images",
        files={"file": ("card.png", b"\x89PNG\r\n\x1a\nexport", "image/png")},
        data={"source": "exported"},
    ).json()
    client.post(f"/api/posts/{post['id']}/publish")
    assert services.publishers["instagram"].calls[-1]["image_url"] == up["public_url"]
