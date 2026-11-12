"""Sensitive-word scan (port of scanText in frontend/src/studio.js).

Sensitive words block publish/schedule. Absolute claims ("保證賺錢") are only warnings,
matching the frontend's behaviour.
"""
import re

DEFAULT_SENSITIVE_WORDS = ["未公開產品", "內部代號", "機密客戶"]
ABSOLUTE_CLAIMS = re.compile(r"保證賺錢|絕對安全|百分之百")


def scan(text: str, words: list[str]) -> dict:
    detected = [w for w in words if w and w in text]
    claims = sorted(set(ABSOLUTE_CLAIMS.findall(text)))
    return {"ok": not detected, "detected": detected, "claims": claims}


def post_text(post: dict) -> str:
    """All user-visible text of a post: title, both captions, and canvas text elements."""
    parts = [post.get("title") or "", post.get("caption_threads") or "", post.get("caption_instagram") or ""]
    canvas = post.get("canvas_json") or {}
    for element in canvas.get("texts") or []:
        if isinstance(element, dict):
            parts.append(str(element.get("text") or ""))
    return "\n".join(parts)
