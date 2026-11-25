"""Sensitive-word scan (same rules as scanText in frontend/src/studio.js).

Sensitive words block submit / approve / publish / schedule (and the publish step itself, so a
word added after scheduling still stops the post). Absolute claims ("保證賺錢") are only warnings,
matching the frontend's behaviour.

Matching is done on a normalized form of both the text and the words, so "SECRET", "Ｓｅｃｒｅｔ",
"機密 客戶" and "機密​客戶" all hit the word "Secret" / "機密客戶":
NFKC (full-width → half-width), case-folded, with whitespace and zero-width characters removed.
"""
import re
import unicodedata

DEFAULT_SENSITIVE_WORDS = ["未公開產品", "內部代號", "機密客戶"]
ABSOLUTE_CLAIMS = re.compile(r"保證賺錢|絕對安全|百分之百")

# whitespace plus the invisible characters people (or copy-paste) put between letters
_IGNORED = re.compile(r"[\s​-‏⁠-⁤﻿­᠎]+")

# canvas_json.texts that the card actually shows (and that end up in the exported image).
# `description` is kept for the bilingual layout but is not drawn, so it is not scanned:
# otherwise publishing would be blocked by a word the user cannot see anywhere.
RENDERED_TEXT_TYPES = frozenset({"headline", "highlight"})


def normalize(text: str) -> str:
    return _IGNORED.sub("", unicodedata.normalize("NFKC", text or "")).casefold()


def scan(text: str, words: list[str]) -> dict:
    haystack = normalize(text)
    detected = []
    for word in words:
        needle = normalize(word)
        if needle and needle in haystack and word not in detected:
            detected.append(word)
    claims = sorted(set(ABSOLUTE_CLAIMS.findall(normalize(text))))
    return {"ok": not detected, "detected": detected, "claims": claims}


def post_text(post: dict) -> str:
    """Everything that is published or shown on the card: title, every caption, card texts."""
    parts = [
        post.get("title") or "",
        post.get("caption_threads") or "",
        post.get("caption_instagram") or "",
        post.get("caption_linkedin") or "",
    ]
    canvas = post.get("canvas_json") or {}
    for element in canvas.get("texts") or []:
        if isinstance(element, dict) and element.get("textType", "headline") in RENDERED_TEXT_TYPES:
            parts.append(str(element.get("text") or ""))
    return "\n".join(parts)
