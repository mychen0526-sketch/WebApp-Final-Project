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
        ai.prompt_image(cand, "isometric", layout, scheme),
    ]
    for p in prompts:
        for leftover in ("{goal}", "{tone}", "{candidate.", "{layout.", "{color_scheme.", "{empty_area}", "{extra}", "{audience}"):
            assert leftover not in p
    assert "left half" in prompts[3] and "isometric" in prompts[3]
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
