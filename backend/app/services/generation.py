"""Copy + card generation for one post (runs as a background task).

Order (Notion §8): layout is fixed first → B captions, D card texts → C text-free image whose
empty area matches the layout. If the user picked one of their own templates, step C is skipped
and the template becomes the card background. Success moves the post generating → editing; any failure moves it
to generation_failed with the reason (E1), never leaving it stuck in generating.

Progress (stage + the Threads caption as it is written) goes to services.progress for the SSE
stream. If the user presses 「停止」, POST /cancel already moved the post out of `generating`;
this task notices at the next step (or mid-stream) and quits without writing anything.
Every successful run is also kept in posts.versions so the editor can switch between them.
"""
import logging
import uuid

from ..schemas import Candidate
from ..state import Status
from ..timeutil import now_iso
from . import design
from .progress import Cancelled, partial_field
from .storage import image_path

log = logging.getLogger(__name__)
MAX_VERSIONS = 10


def build_canvas(design_choice: dict, image_url: str, texts: list[dict]) -> dict:
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
        "texts": texts,
    }


def version_entry(changes: dict, mode: str | None) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "created_at": now_iso(),
        "mode": mode,
        "title": changes["title"],
        "caption_threads": changes["caption_threads"],
        "caption_instagram": changes["caption_instagram"],
        "canvas_json": changes["canvas_json"],
    }


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
        ai = services.ai

        step("copy")
        captions = ai.captions(post["goal"], post.get("tone"), post.get("audience"), candidate, mode, on_text)
        hub.update(post_id, token, threads=captions.threads)
        step("card")
        texts = [t.model_dump() for t in ai.card_texts(candidate, layout, scheme)]
        step("image")
        if design_choice.get("template_id"):
            # the user's own background: no AI image, reuse the stored template file
            url = design_choice["template_url"]
            repo.add_image(post_id, "template", design_choice.get("template_path") or "", url)
        else:
            png = ai.image(candidate, design_choice["visual_style"], layout, scheme)
            step("image")  # the picture can take a while: stop here if the user gave up waiting
            path = image_path(user_id, post_id, "png")
            url = services.storage.upload(path, png, "image/png")
            repo.add_image(post_id, "generated", path, url)
        step("save")

        headline = next((t["text"] for t in texts if t["textType"] == "headline"), candidate.title)
        changes = {
            "status": Status.EDITING.value,
            "title": headline,
            "caption_threads": captions.threads,
            "caption_instagram": captions.instagram,
            "canvas_json": build_canvas(design_choice, url, texts),
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
