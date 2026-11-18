import json

from app.schemas import Candidate, TextElement
from app.services import ai, design


def test_prompts_fill_every_placeholder():
    cand = Candidate(title="t", angle="a", hook="h")
    layout, scheme = design.LAYOUTS["left"], design.COLOR_SCHEMES[1]
    prompts = [
        ai.prompt_candidates("目標", None),
        ai.prompt_captions("目標", "輕鬆分享", None, cand, "short"),
        ai.prompt_card_texts(cand, layout, scheme),
    ]
    for p in prompts:
        for leftover in ("{goal}", "{tone}", "{candidate.", "{layout.", "{color_scheme.", "{empty_area}", "{extra}", "{audience}"):
            assert leftover not in p
    # prompt D example must still be valid JSON after filling
    example = prompts[2][prompts[2].rindex("[") :]
    assert len(json.loads(example.replace("...", "x"))) == 3


def test_enforce_layout_overrides_model_values():
    layout, scheme = design.LAYOUTS["top"], design.COLOR_SCHEMES[0]
    texts = [
        TextElement(textType=t, text="字", position={"x": 1, "y": 1}, fontSize=10, fontFamily="Arial",
                    fontWeight="100", color="#000", alignment="left")
        for t in ("description", "headline", "highlight")
    ]
    fixed = ai.enforce_layout(texts, layout, scheme)
    assert [t.textType for t in fixed] == ["headline", "highlight", "description"]
    assert fixed[0].position.x == 540 and fixed[0].fontSize == 80 and fixed[0].color == scheme.headline


def test_gradient_png_is_valid_png():
    data = ai.gradient_png("#31406a", "#8d84d6", size=8)
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82")


def test_adjust_prompt_fills_every_placeholder():
    from app.schemas import AdjustIn

    body = AdjustIn(
        instruction="改短",
        current={"title": "標", "threads": "文", "palettes": ["墨藍", "松綠"]},
        history=[{"role": "user", "text": "先前"}, {"role": "assistant", "text": "好"}],
    )
    prompt = ai.prompt_adjust(body)
    for leftover in ("{title}", "{threads}", "{instagram}", "{history}", "{instruction}", "{palettes}", "{font}"):
        assert leftover not in prompt
    assert "0 號 墨藍" in prompt and "使用者：先前" in prompt


class _FakeStream:
    status_code = 200

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self.lines


def test_rap_stream_reads_openai_style_chunks(monkeypatch):
    reply = json.dumps({"threads": "第一行\n第二行", "instagram": "IG #AI"}, ensure_ascii=False)
    chunks = [reply[i : i + 5] for i in range(0, len(reply), 5)]
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}" for c in chunks]
    lines = [": keep-alive", *lines, "data: [DONE]"]
    sent = {}

    def fake_stream(method, url, json, headers, timeout):
        sent.update(json)
        return _FakeStream(lines)

    monkeypatch.setattr(ai.httpx, "stream", fake_stream)
    seen = []
    rap = ai.RapAI("key", "https://rap.example/v1", "model")
    captions = rap.captions("目標", None, None, Candidate(title="t", angle="a", hook="h"), on_text=seen.append)
    assert sent["stream"] is True
    assert captions.threads == "第一行\n第二行"
    assert len(seen) == len(chunks) and seen[-1] == reply
