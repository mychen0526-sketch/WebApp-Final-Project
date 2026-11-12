"""Copy + card generation for one post (runs as a background task).

Order (Notion §8): layout is fixed first → B captions, D card texts → C text-free image whose
empty area matches the layout. Success moves the post generating → editing; any failure moves it
to generation_failed with the reason (E1), never leaving it stuck in generating.
"""
import logging

from ..schemas import Candidate
from ..state import Status
from . import design
from .storage import image_path

log = logging.getLogger(__name__)


def build_canvas(design_choice: dict, image_url: str, texts: list[dict]) -> dict:
    return {
        "width": design.CANVAS_SIZE,
        "height": design.CANVAS_SIZE,
        "layout": design_choice["layout"],
        "style": design_choice["style"],
        "visual_style": design_choice["visual_style"],
        "colorScheme": design.COLOR_SCHEMES[design_choice["style"]].name,
        "background": design.COLOR_SCHEMES[design_choice["style"]].primary,
        "image": {"url": image_url, "x": 0, "y": 0, "width": design.CANVAS_SIZE, "height": design.CANVAS_SIZE},
        "texts": texts,
    }


def run_generation(services, user_id: str, post_id: str, design_choice: dict, mode: str | None = None) -> None:
    repo = services.repo
    post = repo.get_post(user_id, post_id)
    if not post or post["status"] != Status.GENERATING:
        return
    try:
        candidate = Candidate.model_validate(post["selected_prompt"])
        layout = design.LAYOUTS[design_choice["layout"]]
        scheme = design.COLOR_SCHEMES[design_choice["style"]]
        ai = services.ai

        captions = ai.captions(post["goal"], post.get("tone"), post.get("audience"), candidate, mode)
        texts = [t.model_dump() for t in ai.card_texts(candidate, layout, scheme)]
        png = ai.image(candidate, design_choice["visual_style"], layout, scheme)

        path = image_path(user_id, post_id, "png")
        url = services.storage.upload(path, png, "image/png")
        repo.add_image(post_id, "generated", path, url)

        headline = next((t["text"] for t in texts if t["textType"] == "headline"), candidate.title)
        repo.update_post(
            user_id,
            post_id,
            {
                "status": Status.EDITING.value,
                "title": headline,
                "caption_threads": captions.threads,
                "caption_instagram": captions.instagram,
                "canvas_json": build_canvas(design_choice, url, texts),
                "generation_error": None,
            },
            expected={Status.GENERATING},
        )
    except Exception as exc:  # noqa: BLE001 - every failure must land in generation_failed
        log.exception("generation failed for post %s", post_id)
        repo.update_post(
            user_id,
            post_id,
            {"status": Status.GENERATION_FAILED.value, "generation_error": str(exc)[:500]},
            expected={Status.GENERATING},
        )
