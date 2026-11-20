"""Text generation on TAIWAN AI RAP, plus a deterministic mock for development and tests.

The card background image is made by FLUX on fal.ai (images.py).

Prompts live in services/prompts/ (one file per prompt, A–D, see the Notion spec §8).
Placeholders look like {goal} or {candidate.title}; they are replaced by plain string
substitution because the prompts also contain literal JSON braces.
"""
import json
import logging
import re
import struct
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import TypeAdapter, ValidationError

from ..schemas import AdjustIn, Adjustment, Candidate, Captions, Reference, TextElement
from . import design

log = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"

REWRITE_HINTS = {
    "short": "請寫得更精簡，保留核心觀點即可。",
    "friendly": "語氣更親切口語，像在跟朋友聊天。",
    "new": "換一種完全不同的寫法與結構，不要沿用上一版的句子。",
}


# Per-language rules filled into prompts B (copy), D (card text) and E (微調).
# Threads allows 500 characters and counts emoji by bytes, so every version keeps a buffer.
LANGUAGE_RULES: dict[str, dict[str, str]] = {
    "zh": {
        "copy": "繁體中文，台灣用語",
        "threads": "380 字以內，不加 hashtag",
        "instagram": "150～300 字，文末加 3～5 個相關 hashtag",
        "linkedin": "全文 400～900 字，文末加 3 個專業 hashtag（例如 #AI #產業趨勢）",
        "card": "全部用繁體中文",
        "headline": "6～14 個字，例如「OpenAI 新公告」",
        "highlight": "6～12 個字，例如「新創的三個機會」",
        "description": "12～24 個字",
        "adjust": "繁體中文，台灣用語",
        "threads_limit": "380 字",
    },
    "en": {
        "copy": "全部用英文撰寫（自然、道地的英文，不是逐字翻譯）；即使發文目標、方向或參考資料是中文，輸出也只能是英文",
        "threads": "450 個字元（characters）以內，不加 hashtag",
        "instagram": "80～180 個英文單字，文末加 3～5 個英文 hashtag",
        "linkedin": "全文 200～450 個英文單字，文末加 3 個英文專業 hashtag（例如 #AI #TechTrends）",
        "card": "全部用英文；公司或產品名稱保留原文",
        "headline": "2～5 個英文單字、28 個字元以內，例如「OpenAI's New Move」",
        "highlight": "2～5 個英文單字、26 個字元以內，例如「3 Chances for Startups」",
        "description": "5～10 個英文單字、55 個字元以內",
        "adjust": "文案維持英文（使用者用中文下指令也一樣）",
        "threads_limit": "450 個字元",
    },
    "both": {
        "copy": "中英雙語：每個平台版本都先寫繁體中文（台灣用語），空一行後寫意思相同的英文版本"
        "（自然的英文，不是逐字翻譯）；hashtag 只放在全文最後",
        "threads": "中文 150 字以內＋英文 220 個字元以內，總長不超過 450 個字元，不加 hashtag",
        "instagram": "中文 100～180 字＋英文 60～120 個單字，全文最後加 4～6 個中英混合 hashtag",
        "linkedin": "中文 300～600 字＋英文 150～300 個單字，全文最後加 3～4 個專業 hashtag",
        "card": "headline 與 highlight 用繁體中文，description 用英文",
        "headline": "繁體中文 6～14 個字，例如「OpenAI 新公告」",
        "highlight": "繁體中文 6～12 個字，例如「新創的三個機會」",
        "description": "英文 5～10 個單字、55 個字元以內（是主標題的英文說明）",
        "adjust": "維持中英雙語：中文在前、英文在後，兩邊意思一致；改動一邊時另一邊也要同步改",
        "threads_limit": "450 個字元",
    },
}


def language_rules(language: str | None) -> dict[str, str]:
    return LANGUAGE_RULES.get(language or "zh", LANGUAGE_RULES["zh"])


class AIError(RuntimeError):
    """Generation failed (API error, timeout, or output that could not be parsed)."""


# Called with the whole reply so far while a streamed reply is being written.
# It may raise (e.g. progress.Cancelled) to stop the request early.
OnText = Callable[[str], None]


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
        self,
        goal: str,
        tone: str | None,
        audience: str | None,
        candidate: Candidate,
        mode: str | None = None,
        on_text: OnText | None = None,
        reference: Reference | None = None,
        language: str = "zh",
    ) -> Captions: ...
    def adjust(self, body: AdjustIn, language: str = "zh") -> Adjustment: ...
    def card_texts(
        self, candidate: Candidate, layout: design.Layout, scheme: design.ColorScheme, language: str = "zh"
    ) -> list[TextElement]: ...
    def image(
        self, candidate: Candidate, visual_style: str, layout: design.Layout, scheme: design.ColorScheme
    ) -> bytes: ...
    def blend(
        self, candidate: Candidate, visual_style: str, layout: design.Layout, scheme: design.ColorScheme, photo: bytes
    ) -> bytes | None: ...


# ---------------------------------------------------------------- prompt builders
def prompt_candidates(goal: str, tone: str | None) -> str:
    return render("a_candidates.txt", {"goal": goal, "tone": tone or "未指定"})


def reference_text(reference: Reference | None) -> str:
    if not reference:
        return "（無，只用發文目標裡的資訊）"
    lines = [f"標題：{reference.title}", f"出處：{reference.source or '未知媒體'}"]
    if reference.published:
        lines.append(f"日期：{reference.published}")
    if reference.summary:
        lines.append(f"摘要：{reference.summary}")
    lines.append(f"網址：{reference.url}")
    return "\n".join(lines)


def prompt_captions(goal, tone, audience, candidate, mode, reference: Reference | None = None, language="zh") -> str:
    rules = language_rules(language)
    return render(
        "b_copy.txt",
        {
            "goal": goal,
            "tone": tone or "未指定",
            "audience": audience or "創業者與科技從業者",
            "extra": REWRITE_HINTS.get(mode or "", "無"),
            "reference": reference_text(reference),
            "language_rule": rules["copy"],
            "threads_rule": rules["threads"],
            "instagram_rule": rules["instagram"],
            "linkedin_rule": rules["linkedin"],
            **candidate_vars(candidate),
        },
    )


def prompt_adjust(body: AdjustIn, language: str = "zh") -> str:
    rules = language_rules(language)
    current = body.current
    palettes = "、".join(f"{i} 號 {name}" for i, name in enumerate(current.palettes)) or "0～3 號"
    history = "\n".join(f"{'使用者' if t.role == 'user' else '助理'}：{t.text}" for t in body.history[-8:]) or "（無）"
    return render(
        "e_adjust.txt",
        {
            "title": current.title or "（空白）",
            "subtitle": current.subtitle or "（空白）",
            "threads": current.threads or "（空白）",
            "instagram": current.instagram or "（空白）",
            "linkedin": current.linkedin or "（空白）",
            "style": str(current.style),
            "palettes": palettes,
            "font": str(current.font),
            "history": history,
            "instruction": body.instruction,
            "language_rule": rules["adjust"],
            "threads_limit": rules["threads_limit"],
        },
    )


def prompt_card_texts(candidate, layout, scheme, language="zh") -> str:
    rules = language_rules(language)
    return render(
        "d_layout.txt",
        {
            **candidate_vars(candidate),
            **design.layout_vars(layout),
            **design.scheme_vars(scheme),
            "language_rule": rules["card"],
            "headline_rule": rules["headline"],
            "highlight_rule": rules["highlight"],
            "description_rule": rules["description"],
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


# ---------------------------------------------------------------- TAIWAN AI RAP
def extract_json(text: str):
    """Parse the first JSON array/object in a chat reply (models sometimes wrap it in ``` fences or prose)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if not starts:
        raise json.JSONDecodeError("no JSON found", text, 0)
    value, _ = json.JSONDecoder().raw_decode(text[min(starts):])
    return value


class RapAI:
    """Text generation on TAIWAN AI RAP (NCHC), an OpenAI-compatible `/chat/completions` API.

    JSON mode (`response_format`) is not used: it only allows objects and some prompts expect arrays,
    so the prompt asks for JSON and `extract_json` reads it back.
    """

    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: int = 90) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds

    def _chat(self, prompt: str, temperature: float = 0.7, on_text: OnText | None = None) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": 4096,
        }
        if on_text is not None:
            return self._chat_stream(body, on_text)
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise AIError(f"LLM 呼叫失敗：{exc}") from exc
        if resp.status_code == 401:
            raise AIError("LLM 呼叫失敗：RAP API 金鑰無效（401）")
        if resp.status_code >= 400:
            raise AIError(f"LLM 呼叫失敗（RAP {resp.status_code}）：{resp.text[:300]}")
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIError(f"LLM 回應格式無法解析：{resp.text[:300]}") from exc

    def _chat_stream(self, body: dict, on_text: OnText) -> str:
        """Same request with `stream: true`; OpenAI-style SSE chunks carry `choices[0].delta.content`."""
        parts: list[str] = []
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json={**body, "stream": True},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            ) as resp:
                if resp.status_code == 401:
                    raise AIError("LLM 呼叫失敗：RAP API 金鑰無效（401）")
                if resp.status_code >= 400:
                    resp.read()
                    raise AIError(f"LLM 呼叫失敗（RAP {resp.status_code}）：{resp.text[:300]}")
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                        continue
                    if delta:
                        parts.append(delta)
                        on_text("".join(parts))
        except httpx.HTTPError as exc:
            raise AIError(f"LLM 呼叫失敗：{exc}") from exc
        return "".join(parts)

    def _json(self, prompt: str, adapter: TypeAdapter, attempts: int = 2, on_text: OnText | None = None):
        last: Exception | None = None
        for _ in range(attempts):
            try:
                return adapter.validate_python(extract_json(self._chat(prompt, on_text=on_text)))
            except (json.JSONDecodeError, ValidationError) as exc:
                log.warning("RAP returned unusable JSON, retrying: %s", exc)
                last = exc
        raise AIError(f"LLM 輸出格式錯誤：{last}")

    def candidates(self, goal, tone):
        result = self._json(prompt_candidates(goal, tone), TypeAdapter(list[Candidate]))
        if len(result) < 3:
            raise AIError("LLM 回傳的候選少於 3 個")
        return result[:3]

    def captions(self, goal, tone, audience, candidate, mode=None, on_text=None, reference=None, language="zh"):
        prompt = prompt_captions(goal, tone, audience, candidate, mode, reference, language)
        return self._json(prompt, TypeAdapter(Captions), on_text=on_text)

    def adjust(self, body, language="zh"):
        return self._json(prompt_adjust(body, language), TypeAdapter(Adjustment))

    def card_texts(self, candidate, layout, scheme, language="zh"):
        texts = self._json(prompt_card_texts(candidate, layout, scheme, language), TypeAdapter(list[TextElement]))
        return enforce_layout(texts, layout, scheme)

    def scene(self, candidate: Candidate, visual_style: str) -> str | None:
        """One English sentence describing the picture, for the English-only image model (FLUX)."""
        prompt = render("c_scene.txt", {**candidate_vars(candidate), "visual_style": design.VISUAL_STYLES[visual_style]})
        try:
            text = self._chat(prompt, temperature=0.9)
        except AIError as exc:  # the image can still be made from the visual style alone
            log.warning("scene prompt failed, falling back to style only: %s", exc)
            return None
        lines = [line.strip().strip('"') for line in text.strip().splitlines() if line.strip()]
        return lines[0][:400] if lines else None


# ---------------------------------------------------------------- Mock
class MockAI:
    """Deterministic output so the full flow works without an API key."""

    def __init__(self, stream_delay: float = 0.0) -> None:
        self.fail_next = False  # tests flip this to simulate E1
        self.stream_delay = stream_delay  # seconds between streamed chunks (0 in tests)

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

    def captions(self, goal, tone, audience, candidate, mode=None, on_text=None, reference=None, language="zh"):
        self._maybe_fail()
        zh = self._zh_captions(candidate, mode, reference)
        if language == "en":
            threads, instagram, linkedin = self._en_captions(candidate, reference)
        elif language == "both":  # Chinese first, then English; hashtags only at the very end
            en = self._en_captions(candidate, reference)
            threads = f"{zh[0]}\n\n{en[0]}"
            instagram = f"{zh[0]}\n\n{en[0]}\n\n#AI #科技趨勢 #TechTrends #Startups"
            linkedin = f"{zh[2].rsplit(chr(10) * 2, 1)[0]}\n\n{en[2]}"
        else:
            threads, instagram, linkedin = zh
        if on_text is not None:  # pretend to stream, a few characters at a time
            raw = json.dumps({"threads": threads, "instagram": instagram, "linkedin": linkedin}, ensure_ascii=False)
            for end in range(4, len(raw) + 4, 4):
                on_text(raw[:end])
                if self.stream_delay:
                    time.sleep(self.stream_delay)
        return Captions(threads=threads, instagram=instagram, linkedin=linkedin)

    @staticmethod
    def _en_captions(candidate, reference) -> tuple[str, str, str]:
        threads = "\n".join(
            [f"Quick take: {candidate.title}", "", "Here is why it matters for teams building with AI.", "", "What do you think? 👇"]
        )
        instagram = threads + "\n\n#AI #TechTrends #Startups"
        cited = f'According to {reference.source or "the report"} ("{reference.title}"), ' if reference else ""
        linkedin = "\n\n".join(
            [
                f"Quick take: {candidate.title}",
                f"{cited}this is worth a closer look.",
                "Why it matters:\n• Product cycles are getting faster\n• The bar for commercialization is moving",
                "How is your team thinking about it?",
                "#AI #TechTrends #Startups",
            ]
        )
        return threads, instagram, linkedin

    @staticmethod
    def _zh_captions(candidate, mode, reference) -> tuple[str, str, str]:
        lines = [candidate.hook, "", candidate.angle + "。", "", "你怎麼看？留言聊聊 👇"]
        if mode == "short":
            lines = [candidate.hook, "", candidate.angle + "。"]
        elif mode == "friendly":
            lines = ["跟你分享一件事 👋", "", *lines]
        elif mode == "new":
            lines = [candidate.angle + "？", "", candidate.hook, "", "想聽聽你的看法 💬"]
        threads = "\n".join(lines)
        instagram = threads + "\n\n#AI #科技趨勢 #新創 #產品開發"
        cited = f"根據{reference.source or '報導'}「{reference.title}」，" if reference else ""
        linkedin = "\n\n".join(
            [
                candidate.hook,
                f"{cited}{candidate.angle}。",
                "為什麼重要：\n• 產品節奏正在變快\n• 商業化的門檻也跟著改變",
                "你的團隊怎麼看？歡迎在留言分享。",
                "#AI #產業趨勢 #新創",
            ]
        )
        return threads, instagram, linkedin

    def adjust(self, body, language="zh"):
        """Keyword rules standing in for the model, so 微調 works without an API key."""
        self._maybe_fail()
        current, text = body.current, body.instruction
        out: dict = {}
        done: list[str] = []
        if "標題" in text and ("問" in text or "？" in text or "?" in text):
            title = current.title.rstrip("。.!！")
            out["title"] = title if title.endswith(("？", "?")) else f"{title}？"
            done.append("標題改成問句")
        if "linkedin" in text.lower() and "正式" in text:
            out["linkedin"] = current.linkedin.replace("！", "。")
            done.append("LinkedIn 語氣改正式")
        if "短" in text:
            paragraphs = current.threads.split("\n\n")
            out["threads"] = (
                "\n\n".join(paragraphs[:2]) if len(paragraphs) > 2 else current.threads[: max(20, len(current.threads) // 2)]
            )
            done.append("Threads 文案縮短")
        if "色" in text or "亮" in text:
            out["style"] = (current.style + 1) % 4
            done.append("換了配色")
        if "大" in text and "字" in text:
            out["font"] = min(44, current.font + 4)
            done.append("標題字放大")
        elif "小" in text and "字" in text:
            out["font"] = max(24, current.font - 4)
            done.append("標題字縮小")
        if not done:
            return Adjustment(reply="示範模式只認得：標題改問句、改短、LinkedIn 改正式、換顏色、字放大／縮小。")
        return Adjustment(reply="已" + "、".join(done) + "。", **out)

    def card_texts(self, candidate, layout, scheme, language="zh"):
        self._maybe_fail()
        headline, highlight, description = candidate.title[:14], candidate.hook[:12], candidate.angle[:24]
        if language == "en":
            headline, highlight = "Quick Take", "Why It Matters"
        if language in ("en", "both"):
            description = "What it means for AI startups"
        raw = [
            TextElement(textType="headline", text=headline, position={"x": 0, "y": 0}, fontSize=80,
                        fontFamily="Noto Sans TC", fontWeight="900", color="#fff", alignment="center"),
            TextElement(textType="highlight", text=highlight, position={"x": 0, "y": 0}, fontSize=48,
                        fontFamily="Noto Sans TC", fontWeight="700", color="#fff", alignment="center"),
            TextElement(textType="description", text=description, position={"x": 0, "y": 0}, fontSize=30,
                        fontFamily="Noto Sans TC", fontWeight="500", color="#fff", alignment="center"),
        ]
        return enforce_layout(raw, layout, scheme)

    def scene(self, candidate, visual_style):
        return None

    def image(self, candidate, visual_style, layout, scheme):
        self._maybe_fail()
        return gradient_png(scheme.primary, scheme.accent, size=design.CANVAS_SIZE)

    def blend(self, candidate, visual_style, layout, scheme, photo):
        return None  # no image model offline: the real photo is used as it is


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
