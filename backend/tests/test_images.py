import base64
import json

import httpx
import pytest

from app.config import Settings
from app.container import build_ai
from app.schemas import Candidate
from app.services import ai, design, images
from app.services.ai import AIError, MockAI, RapAI

PNG = b"\x89PNG\r\n\x1a\nfake"
CAND = Candidate(title="新創的影響", angle="分析公告", hook="先想三件事")
LAYOUT, SCHEME = design.LAYOUTS["top"], design.COLOR_SCHEMES[0]


def route_httpx(monkeypatch, handler):
    """Send every httpx call (Client and module-level post) through `handler`."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    def post(url, **kwargs):
        timeout = kwargs.pop("timeout", None)
        with real_client(transport=transport, timeout=timeout) as c:
            return c.post(url, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(httpx, "post", post)


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


# ---------------------------------------------------------------- RAP text
def test_extract_json_handles_fences_and_prose():
    assert ai.extract_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert ai.extract_json('好的，以下是結果：\n{"threads": "x", "instagram": "y"}\n謝謝') == {"threads": "x", "instagram": "y"}


def test_rap_candidates_request_and_parse(monkeypatch):
    seen = {}
    items = [{"title": f"t{i}", "angle": "a", "hook": "h"} for i in range(3)]

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return chat_reply("```json\n" + json.dumps(items, ensure_ascii=False) + "\n```")

    route_httpx(monkeypatch, handler)
    rap = RapAI("k", "https://rap.example/api/v1/", "gemma-4-31B-it")
    assert [c.title for c in rap.candidates("目標", None)] == ["t0", "t1", "t2"]
    assert seen["url"] == "https://rap.example/api/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "gemma-4-31B-it" and seen["body"]["messages"][0]["role"] == "user"


def test_rap_retries_bad_json_then_fails(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return chat_reply("抱歉，我無法回答")

    route_httpx(monkeypatch, handler)
    with pytest.raises(AIError, match="格式錯誤"):
        RapAI("k", "https://rap.example/v1", "m").captions("g", None, None, CAND)
    assert len(calls) == 2


def test_rap_bad_key_is_clear_error(monkeypatch):
    route_httpx(monkeypatch, lambda r: httpx.Response(401, json={"message": "Not authenticated"}))
    with pytest.raises(AIError, match="金鑰無效"):
        RapAI("bad", "https://rap.example/v1", "m").candidates("g", None)


def test_rap_scene_failure_is_not_fatal(monkeypatch):
    route_httpx(monkeypatch, lambda r: httpx.Response(500, text="boom"))
    assert RapAI("k", "https://rap.example/v1", "m").scene(CAND, "abstract") is None


# ---------------------------------------------------------------- fal image
def test_flux_prompt_is_english_and_filled():
    p = images.prompt_flux(None, "geometric", design.LAYOUTS["left"], SCHEME)
    assert "{" not in p and "left half" in p and "geometric" in p
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in p)


def test_fal_uses_scene_from_text_model(monkeypatch):
    seen = {}

    def handler(request):
        if "fal.run" in str(request.url):
            seen["auth"] = request.headers["authorization"]
            seen["url"] = str(request.url)
            seen["prompt"] = json.loads(request.content)["prompt"]
            uri = "data:image/png;base64," + base64.b64encode(PNG).decode()
            return httpx.Response(200, json={"images": [{"url": uri}]})
        return chat_reply("A glowing seed sprouting circuit-board roots in soft light")

    route_httpx(monkeypatch, handler)
    svc = images.FluxImageAI(RapAI("k", "https://rap.example/v1", "m"), images.FalFlux("fk"))
    assert svc.image(CAND, "abstract", LAYOUT, SCHEME) == PNG
    assert seen["auth"] == "Key fk" and seen["url"] == "https://fal.run/fal-ai/flux/schnell"
    assert seen["prompt"].startswith("A glowing seed sprouting")


def test_fal_error_becomes_ai_error(monkeypatch):
    route_httpx(monkeypatch, lambda r: httpx.Response(403, text="Exhausted balance"))
    with pytest.raises(AIError, match="403"):
        images.FalFlux("k").generate("p")


def test_no_fal_key_gives_gradient():
    png = images.FluxImageAI(MockAI(), None).image(CAND, "abstract", LAYOUT, SCHEME)
    assert png.startswith(b"\x89PNG")


# ---------------------------------------------------------------- wiring
@pytest.mark.parametrize(
    "env, text_type, image_backend",
    [
        ({}, MockAI, "mock"),
        ({"rap_api_key": "r"}, RapAI, None),
        ({"fal_api_key": "f"}, MockAI, images.FalFlux),
        ({"rap_api_key": "r", "fal_api_key": "f"}, RapAI, images.FalFlux),
        ({"rap_api_key": "r", "fal_api_key": "f", "mock_ai": True}, MockAI, "mock"),
    ],
)
def test_build_ai(env, text_type, image_backend):
    built = build_ai(Settings(_env_file=None, **env))
    if image_backend == "mock":
        assert isinstance(built, MockAI)
        return
    assert isinstance(built, images.FluxImageAI) and isinstance(built.text, text_type)
    assert built.backend is None if image_backend is None else isinstance(built.backend, image_backend)
