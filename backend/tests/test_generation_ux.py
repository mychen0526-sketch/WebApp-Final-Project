"""Streaming progress, 停止 (cancel), versions, and AI 微調 (adjust)."""
import json

from app.services import design
from app.services.generation import run_generation
from app.services.progress import partial_field

from .conftest import CANDIDATE, USER, create_post


def _generating_post(services, **extra) -> dict:
    return services.repo.create_post(
        {"user_id": USER, "goal": "目標", "selected_prompt": CANDIDATE, "status": "generating", **extra}
    )


def _sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_partial_field_reads_unfinished_json():
    assert partial_field('{"threads": "第一行\\n第二', "threads") == "第一行\n第二"
    assert partial_field('{"threads": "完整", "instagram": "x"}', "threads") == "完整"
    assert partial_field('{"thr', "threads") == ""


def test_every_generation_is_kept_as_a_version(client):
    post = create_post(client)
    assert len(post["versions"]) == 1
    assert post["versions"][0]["caption_threads"] == post["caption_threads"]

    resp = client.post(f"/api/posts/{post['id']}/generate", json={"mode": "short"})
    assert resp.status_code == 202
    again = client.get(f"/api/posts/{post['id']}").json()
    assert [v["mode"] for v in again["versions"]] == [None, "short"]
    assert again["versions"][1]["caption_threads"] == again["caption_threads"] != post["caption_threads"]


def test_versions_cannot_be_patched_by_the_client(client):
    post = create_post(client)
    resp = client.patch(f"/api/posts/{post['id']}", json={"versions": []})
    assert resp.status_code == 422


def test_stream_ends_with_done_and_the_post(client):
    post = create_post(client)
    resp = client.get(f"/api/posts/{post['id']}/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(resp.text)
    assert events[-1][0] == "done"
    assert events[-1][1]["post"]["status"] == "editing"


def test_progress_records_the_caption_while_it_is_written(services):
    post = _generating_post(services)
    seen: list[str] = []
    original = services.progress.update

    def spy(post_id, token, **changes):
        if "threads" in changes:
            seen.append(changes["threads"])
        original(post_id, token, **changes)

    services.progress.update = spy
    run_generation(services, USER, post["id"], design.resolve(None, None, None))
    assert services.repo.get_post(USER, post["id"])["status"] == "editing"
    assert len(seen) > 3 and seen[0] != seen[-1]
    assert all(seen[-1].startswith(s) for s in seen[:-1])


def test_cancel_first_generation_ends_as_failed(client, services):
    post = _generating_post(services)
    services.progress.start(post["id"])
    resp = client.post(f"/api/posts/{post['id']}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "generation_failed"
    assert resp.json()["generation_error"] == "已停止生成"


def test_cancel_rewrite_goes_back_to_editing(client, services):
    post = _generating_post(services, caption_threads="舊文案", caption_instagram="舊 IG")
    resp = client.post(f"/api/posts/{post['id']}/cancel")
    assert resp.json()["status"] == "editing"
    assert resp.json()["caption_threads"] == "舊文案"


def test_cancel_only_while_generating(client):
    post = create_post(client)
    assert client.post(f"/api/posts/{post['id']}/cancel").status_code == 409


def test_stopped_generation_writes_nothing(services):
    """The user stops mid-stream: the task quits and leaves the cancelled post alone."""
    post = _generating_post(services, caption_threads="舊文案")
    token = services.progress.start(post["id"])
    original = services.progress.update
    calls = {"n": 0}

    def stop_after_a_few(post_id, tok, **changes):
        calls["n"] += 1
        if calls["n"] == 3:  # what POST /cancel does
            services.repo.update_post(USER, post_id, {"status": "editing"})
            services.progress.cancel(post_id)
        original(post_id, tok, **changes)

    services.progress.update = stop_after_a_few
    run_generation(services, USER, post["id"], design.resolve(None, None, None), None, token)
    after = services.repo.get_post(USER, post["id"])
    assert after["status"] == "editing"
    assert after["caption_threads"] == "舊文案"
    assert after["versions"] == []
    assert services.progress.get(post["id"]).done


def test_a_newer_run_replaces_an_older_one(services):
    post = _generating_post(services)
    old = services.progress.start(post["id"])
    services.progress.start(post["id"])  # regenerate again before the first run started
    run_generation(services, USER, post["id"], design.resolve(None, None, None), None, old)
    assert services.repo.get_post(USER, post["id"])["status"] == "generating"  # left for the new run


def test_adjust_returns_only_changed_fields(client):
    post = create_post(client)
    body = {
        "instruction": "把標題改成問句",
        "current": {"title": "新創的影響", "threads": post["caption_threads"], "style": 0, "font": 30},
    }
    resp = client.post(f"/api/posts/{post['id']}/adjust", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "新創的影響？"
    assert set(data) == {"reply", "title"}
    # nothing saved yet
    assert client.get(f"/api/posts/{post['id']}").json()["title"] != "新創的影響？"


def test_adjust_unknown_request_explains_itself(client):
    post = create_post(client)
    resp = client.post(f"/api/posts/{post['id']}/adjust", json={"instruction": "寫一首詩", "current": {}})
    assert set(resp.json()) == {"reply"}


def test_adjust_only_for_drafts(client):
    from .conftest import to_pending

    post = to_pending(client)
    resp = client.post(f"/api/posts/{post['id']}/adjust", json={"instruction": "改短", "current": {}})
    assert resp.status_code == 409
