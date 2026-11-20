"""Copy language: 繁體中文 / English / 中英雙語, chosen per post and kept on regenerate and 微調."""
import json
import re

import pytest

from app.schemas import AdjustIn, Candidate
from app.services import ai, design

from .conftest import create_post

REFERENCE = {
    "title": "Starship caught by the tower",
    "url": "https://news.example.com/starship",
    "source": "Example News",
    "summary": "The upper stage was caught for the first time.",
}
PLACEHOLDER = re.compile(r"\{[a-z_.]+\}")


@pytest.mark.parametrize("language", ["zh", "en", "both"])
def test_prompts_fill_language_placeholders(language):
    cand = Candidate(title="t", angle="a", hook="h")
    layout, scheme = design.LAYOUTS["top"], design.COLOR_SCHEMES[0]
    copy = ai.prompt_captions("目標", None, None, cand, None, None, language)
    card = ai.prompt_card_texts(cand, layout, scheme, language)
    adjust = ai.prompt_adjust(AdjustIn(instruction="改短", current={"title": "x"}), language)
    for prompt in (copy, card, adjust):
        assert not PLACEHOLDER.search(prompt.replace('{"', "").replace("{...}", "")), PLACEHOLDER.findall(prompt)
    rules = ai.LANGUAGE_RULES[language]
    assert rules["copy"] in copy and rules["threads"] in copy and rules["card"] in card and rules["adjust"] in adjust
    # prompt D's example must still be valid JSON after filling
    assert len(json.loads(card[card.rindex("[") :].replace("...", "x"))) == 3


def test_unknown_language_falls_back_to_chinese():
    assert ai.language_rules("fr") is ai.LANGUAGE_RULES["zh"]
    assert ai.language_rules(None) is ai.LANGUAGE_RULES["zh"]


def test_default_post_is_chinese(client):
    post = create_post(client)
    assert post["canvas_json"]["language"] == "zh"
    assert "你怎麼看" in post["caption_threads"]


def test_english_post(client):
    post = create_post(client, language="en", reference=REFERENCE, image_mode="ai")
    assert post["status"] == "editing", post.get("generation_error")
    assert post["canvas_json"]["language"] == "en"
    assert post["caption_threads"].startswith("Quick take:")
    assert "Source: Example News https://news.example.com/starship" in post["caption_linkedin"]
    assert "資料來源" not in post["caption_linkedin"]
    texts = {t["textType"]: t["text"] for t in post["canvas_json"]["texts"]}
    assert texts["headline"] == "Quick Take"


def test_bilingual_post_has_chinese_then_english(client):
    post = create_post(client, language="both")
    threads = post["caption_threads"]
    assert threads.index("你怎麼看") < threads.index("Quick take:")
    assert len(threads) <= 500
    texts = {t["textType"]: t["text"] for t in post["canvas_json"]["texts"]}
    assert texts["description"] == "What it means for AI startups"  # English line under a Chinese headline
    assert post["caption_instagram"].rstrip().endswith("#Startups")  # hashtags only at the very end


def test_regenerate_keeps_language_unless_changed(client):
    post = create_post(client, language="en")
    again = client.post(f"/api/posts/{post['id']}/generate", json={"mode": "short"})
    assert again.status_code == 202, again.text
    post = client.get(f"/api/posts/{post['id']}").json()
    assert post["canvas_json"]["language"] == "en" and post["caption_threads"].startswith("Quick take:")

    switched = client.post(f"/api/posts/{post['id']}/generate", json={"language": "zh"})
    assert switched.status_code == 202, switched.text
    post = client.get(f"/api/posts/{post['id']}").json()
    assert post["canvas_json"]["language"] == "zh" and "你怎麼看" in post["caption_threads"]


def test_adjust_uses_post_language(client, services, monkeypatch):
    seen = {}
    original = services.ai.adjust

    def spy(body, language="zh"):
        seen["language"] = language
        return original(body, language)

    monkeypatch.setattr(services.ai, "adjust", spy)
    post = create_post(client, language="both")
    resp = client.post(f"/api/posts/{post['id']}/adjust", json={"instruction": "改短", "current": {"threads": "a\n\nb\n\nc"}})
    assert resp.status_code == 200, resp.text
    assert seen["language"] == "both"


def test_rejects_unknown_language(client):
    body = {"goal": "目標", "selected": {"title": "t", "angle": "a", "hook": "h"}, "language": "fr"}
    assert client.post("/api/posts", json=body).status_code == 422
