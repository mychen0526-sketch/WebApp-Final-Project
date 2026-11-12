"""LLM and image generation: Gemini, plus a deterministic mock for development and tests.

Prompts live in services/prompts/ (one file per prompt, A–D, see the Notion spec §8).
Placeholders look like {goal} or {candidate.title}; they are replaced by plain string
substitution because the prompts also contain literal JSON braces.
"""
import json
import logging
import struct
import zlib
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from ..schemas import Candidate, Captions, TextElement
from . import design

log = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"

REWRITE_HINTS = {
    "short": "請寫得更精簡，保留核心觀點即可。",
    "friendly": "語氣更親切口語，像在跟朋友聊天。",
    "new": "換一種完全不同的寫法與結構，不要沿用上一版的句子。",
}


class AIError(RuntimeError):
    """Generation failed (API error, timeout, or output that could not be parsed)."""


def render(template_name: str, values: dict[str, str]) -> str:
    text = (PROMPT_DIR / template_name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def candidate_vars(candidate: Candidate) -> dict[str, str]:
    return {"candidate.title": candidate.title, "candidate.angle": candidate.angle, "candidate.hook": candidate.hook}


class AIService(Protocol):
    def candidates(self, goal: str, tone: str | None) -> list[Candidate]: ...
    def captions(
        self, goal: str, tone: str | None, audience: str | None, candidate: Candidate, mode: str | None = None
    ) -> Captions: ...
    def card_texts(self, candidate: Candidate, layout: design.Layout, scheme: design.ColorScheme) -> list[TextElement]: ...
    def image(
        self, candidate: Candidate, visual_style: str, layout: design.Layout, scheme: design.ColorScheme
    ) -> bytes: ...


# ---------------------------------------------------------------- prompt builders
def prompt_candidates(goal: str, tone: str | None) -> str:
    return render("a_candidates.txt", {"goal": goal, "tone": tone or "未指定"})


def prompt_captions(goal, tone, audience, candidate, mode) -> str:
    return render(
        "b_copy.txt",
        {
            "goal": goal,
            "tone": tone or "未指定",
            "audience": audience or "創業者與科技從業者",
            "extra": REWRITE_HINTS.get(mode or "", "無"),
            **candidate_vars(candidate),
        },
    )


def prompt_card_texts(candidate, layout, scheme) -> str:
    return render("d_layout.txt", {**candidate_vars(candidate), **design.layout_vars(layout), **design.scheme_vars(scheme)})


def prompt_image(candidate, visual_style, layout, scheme) -> str:
    return render(
        "c_image.txt",
        {
            **candidate_vars(candidate),
            "visual_style": design.VISUAL_STYLES[visual_style],
            **design.layout_vars(layout),
            **design.scheme_vars(scheme),
        },
    )


def enforce_layout(texts: list[TextElement], layout: design.Layout, scheme: design.ColorScheme) -> list[TextElement]:
    """Prompt D asks the model to copy coordinates/colors verbatim; enforce them anyway."""
    spec = {
        "headline": (layout.headline, 80, "900", scheme.headline),
        "highlight": (layout.highlight, 48, "700", scheme.highlight),
        "description": (layout.desc, 30, "500", scheme.description),
    }
    by_type = {t.textType: t for t in texts}
    missing = set(spec) - set(by_type)
    if missing:
        raise AIError(f"圖上文字缺少 {sorted(missing)}")
    return [
        TextElement(
            textType=text_type,
            text=by_type[text_type].text,
            position={"x": pos[0], "y": pos[1]},
            fontSize=size,
            fontFamily="Noto Sans TC",
            fontWeight=weight,
            color=color,
            alignment=layout.alignment,
        )
        for text_type, (pos, size, weight, color) in spec.items()
    ]


# ---------------------------------------------------------------- Gemini
class GeminiAI:
    def __init__(self, api_key: str, text_model: str, image_model: str, timeout_seconds: int = 90) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_seconds * 1000))
        self.text_model = text_model
        self.image_model = image_model

    def _json(self, prompt: str, adapter: TypeAdapter, attempts: int = 2):
        last: Exception | None = None
        for _ in range(attempts):
            try:
                resp = self.client.models.generate_content(
                    model=self.text_model,
                    contents=prompt,
                    config=self._types.GenerateContentConfig(response_mime_type="application/json"),
                )
                return adapter.validate_python(json.loads(resp.text or ""))
            except (json.JSONDecodeError, ValidationError) as exc:
                log.warning("Gemini returned unusable JSON, retrying: %s", exc)
                last = exc
            except Exception as exc:  # API / network error
                raise AIError(f"LLM 呼叫失敗：{exc}") from exc
        raise AIError(f"LLM 輸出格式錯誤：{last}")

    def candidates(self, goal, tone):
        result = self._json(prompt_candidates(goal, tone), TypeAdapter(list[Candidate]))
        if len(result) < 3:
            raise AIError("LLM 回傳的候選少於 3 個")
        return result[:3]

    def captions(self, goal, tone, audience, candidate, mode=None):
        return self._json(prompt_captions(goal, tone, audience, candidate, mode), TypeAdapter(Captions))

    def card_texts(self, candidate, layout, scheme):
        texts = self._json(prompt_card_texts(candidate, layout, scheme), TypeAdapter(list[TextElement]))
        return enforce_layout(texts, layout, scheme)

    def image(self, candidate, visual_style, layout, scheme):
        types = self._types
        try:
            resp = self.client.models.generate_content(
                model=self.image_model,
                contents=prompt_image(candidate, visual_style, layout, scheme),
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="1:1"),
                ),
            )
        except Exception as exc:
            raise AIError(f"圖片生成失敗：{exc}") from exc
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else None) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        raise AIError("圖片生成沒有回傳圖片")


# ---------------------------------------------------------------- Mock
class MockAI:
    """Deterministic output so the full flow works without an API key."""

    def __init__(self) -> None:
        self.fail_next = False  # tests flip this to simulate E1

    def _maybe_fail(self):
        if self.fail_next:
            self.fail_next = False
            raise AIError("模擬的生成失敗")

    def candidates(self, goal, tone):
        self._maybe_fail()
        topic = goal.strip().replace("\n", " ")[:20]
        return [
            Candidate(title="事件重點整理", angle=f"用三個重點說清楚「{topic}」發生了什麼", hook="先講結論：這件事值得注意"),
            Candidate(title="新創的影響", angle=f"分析「{topic}」對 AI 新創商業化的影響", hook="如果你是新創，這三件事要先想"),
            Candidate(title="觀點與預測", angle=f"從「{topic}」推演接下來半年的產業走向", hook="我的預測可能不太一樣"),
        ]

    def captions(self, goal, tone, audience, candidate, mode=None):
        self._maybe_fail()
        lines = [candidate.hook, "", candidate.angle + "。", "", "你怎麼看？留言聊聊 👇"]
        if mode == "short":
            lines = [candidate.hook, "", candidate.angle + "。"]
        threads = "\n".join(lines)
        instagram = threads + "\n\n#AI #科技趨勢 #新創 #產品開發"
        return Captions(threads=threads, instagram=instagram)

    def card_texts(self, candidate, layout, scheme):
        self._maybe_fail()
        raw = [
            TextElement(textType="headline", text=candidate.title[:14], position={"x": 0, "y": 0}, fontSize=80,
                        fontFamily="Noto Sans TC", fontWeight="900", color="#fff", alignment="center"),
            TextElement(textType="highlight", text=candidate.hook[:12], position={"x": 0, "y": 0}, fontSize=48,
                        fontFamily="Noto Sans TC", fontWeight="700", color="#fff", alignment="center"),
            TextElement(textType="description", text=candidate.angle[:24], position={"x": 0, "y": 0}, fontSize=30,
                        fontFamily="Noto Sans TC", fontWeight="500", color="#fff", alignment="center"),
        ]
        return enforce_layout(raw, layout, scheme)

    def image(self, candidate, visual_style, layout, scheme):
        self._maybe_fail()
        return gradient_png(scheme.primary, scheme.accent, size=design.CANVAS_SIZE)


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def gradient_png(top: str, bottom: str, size: int = 1080) -> bytes:
    """Vertical-gradient PNG built with zlib only (no Pillow)."""
    a, b = _hex(top), _hex(bottom)
    rows = []
    for y in range(size):
        t = y / max(size - 1, 1)
        pixel = bytes(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
        rows.append(b"\x00" + pixel * size)
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
