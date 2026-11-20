"""Copy + card generation for one post (runs as a background task).

Order (Notion §8): layout is fixed first → B captions, D card texts → C text-free image whose
empty area matches the layout. If the user picked one of their own templates, step C is skipped
and the template becomes the card background. Success moves the post generating → editing; any failure moves it
to generation_failed with the reason (E1), never leaving it stuck in generating.

Progress (stage + the Threads caption as it is written) goes to services.progress for the SSE
stream. If the user presses 「停止」, POST /cancel already moved the post out of `generating`;
this task notices at the next step (or mid-stream) and quits without writing anything.
Every successful run is also kept in posts.versions so the editor can switch between them.

Real pictures (趨勢情報): when the design choice carries a `reference` (a news article found by
search) with an image and `image_mode` is photo / blend, step C downloads that picture (SSRF-safe,
normalized to 1080² JPEG) and either uses it as the background (photo) or repaints it with FLUX
image-to-image (blend). The publisher is credited on the card and the article is linked in the
LinkedIn / Threads copy. If the picture cannot be used, the card falls back to an AI background and
`canvas_json.image_note` says why.
"""
import logging
import uuid

from ..schemas import Candidate, Reference
from ..state import Status
from ..timeutil import now_iso
from . import design
from .progress import Cancelled, partial_field
from .research import ResearchError, fetch_picture
from .storage import image_path

log = logging.getLogger(__name__)
MAX_VERSIONS = 10
THREADS_MAX_CHARS = 500


def build_canvas(design_choice: dict, image_url: str, texts: list[dict], picture: dict | None = None) -> dict:
    picture = picture or {}
    return {
        "width": design.CANVAS_SIZE,
        "height": design.CANVAS_SIZE,
        "layout": design_choice["layout"],
        "style": design_choice["style"],
        "visual_style": design_choice["visual_style"],
        "colorScheme": design.COLOR_SCHEMES[design_choice["style"]].name,
        "background": design.COLOR_SCHEMES[design_choice["style"]].primary,
        "template_id": design_choice.get("template_id"),
        "template_path": design_choice.get("template_path"),
        "image": {"url": image_url, "x": 0, "y": 0, "width": design.CANVAS_SIZE, "height": design.CANVAS_SIZE},
        "image_mode": picture.get("mode") or "ai",
        "reference": design_choice.get("reference"),
        "language": design_choice.get("language") or "zh",
        "credit": picture.get("credit"),
        "image_note": picture.get("note"),
        "texts": texts,
    }


# Labels written into the copy / onto the card, per post language.
SOURCE_LABEL = {"zh": "資料來源：", "en": "Source: ", "both": "資料來源 Source："}
CREDIT_LABEL = {"zh": "圖片來源：", "en": "Photo: ", "both": "圖片來源 Photo："}


def credit_of(reference: Reference, language: str = "zh") -> str:
    label = CREDIT_LABEL.get(language, CREDIT_LABEL["zh"])
    return f"{label}{reference.source or reference.url.split('/')[2]}"


def with_source(text: str, reference: Reference | None, limit: int | None = None, language: str = "zh") -> str:
    """Append the article link (once) so readers can check the source."""
    if not reference or not text or reference.url in text:
        return text
    name = reference.source or ("original" if language == "en" else "原文")
    label = SOURCE_LABEL.get(language, SOURCE_LABEL["zh"])
    out = f"{text.rstrip()}\n\n{label}{name} {reference.url}"
    return out if limit is None or len(out) <= limit else text


def version_entry(changes: dict, mode: str | None) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "created_at": now_iso(),
        "mode": mode,
        "title": changes["title"],
        "caption_threads": changes["caption_threads"],
        "caption_instagram": changes["caption_instagram"],
        "caption_linkedin": changes.get("caption_linkedin"),
        "canvas_json": changes["canvas_json"],
    }


def make_picture(services, user_id: str, post_id: str, candidate: Candidate, design_choice: dict, step) -> tuple[str, dict]:
    """Step C. Returns (background URL, picture info for the canvas)."""
    repo, ai = services.repo, services.ai
    layout = design.LAYOUTS[design_choice["layout"]]
    scheme = design.COLOR_SCHEMES[design_choice["style"]]
    if design_choice.get("template_id"):
        # the user's own background: no AI image, reuse the stored template file
        url = design_choice["template_url"]
        repo.add_image(post_id, "template", design_choice.get("template_path") or "", url)
        return url, {"mode": "template"}

    note = None
    mode = design_choice.get("image_mode") or "ai"
    reference = Reference.model_validate(design_choice["reference"]) if design_choice.get("reference") else None
    if mode in ("photo", "blend") and reference and reference.image_url:
        try:
            photo = fetch_picture(services.fetcher, reference.image_url)
            step("image")
            path = image_path(user_id, post_id, "jpg")
            photo_url = services.storage.upload(path, photo, "image/jpeg")
            repo.add_image(post_id, "reference", path, photo_url)
            language = design_choice.get("language") or "zh"
            info = {"mode": "photo", "credit": credit_of(reference, language)}
            if mode == "blend":
                blended = ai.blend(candidate, design_choice["visual_style"], layout, scheme, photo)
                step("image")
                if blended is None:
                    info["note"] = "沒有設定圖片模型（FAL_API_KEY），直接使用新聞原圖"
                    return photo_url, info
                path = image_path(user_id, post_id, "png")
                url = services.storage.upload(path, blended, "image/png")
                repo.add_image(post_id, "generated", path, url)
                return url, {"mode": "blend", "credit": f"{credit_of(reference, language)}（AI 融合）"}
            return photo_url, info
        except ResearchError as exc:
            log.warning("reference picture unusable for post %s: %s", post_id, exc)
            note = f"新聞圖片無法使用，已改用 AI 底圖（{exc}）"
            mode = "ai"
    elif mode in ("photo", "blend"):
        note = "這則參考資料沒有圖片，已改用 AI 底圖"
        mode = "ai"

    png = ai.image(candidate, design_choice["visual_style"], layout, scheme)
    step("image")  # the picture can take a while: stop here if the user gave up waiting
    path = image_path(user_id, post_id, "png")
    url = services.storage.upload(path, png, "image/png")
    repo.add_image(post_id, "generated", path, url)
    return url, {"mode": mode, "note": note}


def run_generation(
    services,
    user_id: str,
    post_id: str,
    design_choice: dict,
    mode: str | None = None,
    token: str | None = None,
) -> None:
    repo = services.repo
    hub = services.progress
    token = token or hub.start(post_id)
    post = repo.get_post(user_id, post_id)
    if not post or post["status"] != Status.GENERATING:
        hub.finish(post_id, token)
        return

    def step(stage: str) -> None:
        hub.update(post_id, token, stage=stage)

    def on_text(raw: str) -> None:
        hub.update(post_id, token, threads=partial_field(raw, "threads"))

    try:
        candidate = Candidate.model_validate(post["selected_prompt"])
        layout = design.LAYOUTS[design_choice["layout"]]
        scheme = design.COLOR_SCHEMES[design_choice["style"]]
        reference = Reference.model_validate(design_choice["reference"]) if design_choice.get("reference") else None
        language = design_choice.get("language") or "zh"
        ai = services.ai

        step("copy")
        captions = ai.captions(
            post["goal"], post.get("tone"), post.get("audience"), candidate, mode, on_text,
            reference=reference, language=language,
        )
        hub.update(post_id, token, threads=captions.threads)
        step("card")
        texts = [t.model_dump() for t in ai.card_texts(candidate, layout, scheme, language)]
        step("image")
        url, picture = make_picture(services, user_id, post_id, candidate, design_choice, step)
        step("save")

        headline = next((t["text"] for t in texts if t["textType"] == "headline"), candidate.title)
        linkedin = captions.linkedin.strip() or captions.instagram
        changes = {
            "status": Status.EDITING.value,
            "title": headline,
            "caption_threads": with_source(captions.threads, reference, THREADS_MAX_CHARS, language),
            "caption_instagram": captions.instagram,
            "caption_linkedin": with_source(linkedin, reference, language=language),
            "canvas_json": build_canvas(design_choice, url, texts, picture),
            "generation_error": None,
        }
        versions = list(post.get("versions") or [])[-(MAX_VERSIONS - 1) :]
        changes["versions"] = [*versions, version_entry(changes, mode)]
        repo.update_post(user_id, post_id, changes, expected={Status.GENERATING})
    except Cancelled:
        log.info("generation for post %s was stopped", post_id)
    except Exception as exc:  # noqa: BLE001 - every failure must land in generation_failed
        log.exception("generation failed for post %s", post_id)
        repo.update_post(
            user_id,
            post_id,
            {"status": Status.GENERATION_FAILED.value, "generation_error": str(exc)[:500]},
            expected={Status.GENERATING},
        )
    finally:
        hub.finish(post_id, token)
