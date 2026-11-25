"""Lambda mode: background work goes out as signed async invocations; the events path runs it."""
import json
import sys
import types

from app.jobs import LAMBDA_EVENTS_PATH, sign

from .conftest import CANDIDATE, USER


def _create(client):
    body = {"goal": "介紹新功能", "selected": CANDIDATE}
    response = client.post("/api/posts", json=body, headers={"X-Dev-User": USER})
    assert response.status_code == 202, response.text
    return response.json()


def test_lambda_dispatch_invokes_async_and_event_runs_job(client, services, monkeypatch):
    sent = []

    class FakeLambda:
        def invoke(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "social-api")
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name: FakeLambda()))

    post = _create(client)
    assert len(sent) == 1 and sent[0]["InvocationType"] == "Event"
    event = json.loads(sent[0]["Payload"])
    assert event["job"] == "generate" and event["args"]["post_id"] == post["id"]
    # nothing ran in-process
    assert services.repo.get_post(USER, post["id"])["status"] == "generating"

    response = client.post(LAMBDA_EVENTS_PATH, json=event)
    assert response.status_code == 200, response.text
    assert services.repo.get_post(USER, post["id"])["status"] == "editing"


def test_events_path_rejects_forged_jobs(client, services):
    args = {"user_id": USER, "post_id": "x", "choice": {}, "mode": None}
    assert client.post(LAMBDA_EVENTS_PATH, json={"job": "generate", "args": args, "sig": "0" * 64}).status_code == 403
    assert client.post(LAMBDA_EVENTS_PATH, json={"job": "generate", "args": args}).status_code == 403
    assert client.post(LAMBDA_EVENTS_PATH, json={"job": "rm -rf"}).status_code == 403
    good = sign(services, "publish", {"user_id": USER, "post_id": "missing"})
    tampered = {"user_id": "someone-else", "post_id": "missing"}
    assert client.post(LAMBDA_EVENTS_PATH, json={"job": "publish", "args": tampered, "sig": good}).status_code == 403


def test_schedule_events_need_no_signature(client):
    assert client.post(LAMBDA_EVENTS_PATH, json={"job": "tick"}).json() == {"ok": True, "job": "tick"}
    assert client.post(LAMBDA_EVENTS_PATH, json={"job": "refresh_tokens"}).status_code == 200
