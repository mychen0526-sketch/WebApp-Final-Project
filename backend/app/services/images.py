"""Text-free card backgrounds from FLUX.1 [schnell] on fal.ai.

The card's words are drawn by the frontend on top of the picture, so the image model never has to
render text. That lets us use the cheapest fast diffusion model.

FLUX reads English and has no negative prompt: words like "no text" tend to *add* text, so the
prompt only describes what we want. The post topic is Chinese, so an English scene sentence is
written by the text LLM first (`scene`); without one we fall back to the visual style.

「AI 融合」(`blend`) starts from a real news photo instead of noise: FLUX [dev] image-to-image
keeps the photo's subject and composition and repaints it in the post's style and colors.
"""
import base64
import logging

import httpx

from . import design
from .ai import AIError, gradient_png, render

log = logging.getLogger(__name__)

IMAGE_SIZE = 1024  # FLUX wants multiples of 16; the canvas scales it to 1080


def prompt_blend(scene: str | None, visual_style: str, layout: design.Layout, scheme: design.ColorScheme) -> str:
    return render(
        "c_image_blend.txt",
        {
            "scene": scene or "the main subject of the photo",
            "visual_style": design.VISUAL_STYLES[visual_style],
            "empty_area": layout.empty_area,
            "color_scheme.mood": scheme.mood,
        },
    )


def prompt_flux(scene: str | None, visual_style: str, layout: design.Layout, scheme: design.ColorScheme) -> str:
    return render(
        "c_image_flux.txt",
        {
            "scene": scene or "a single abstract concept about technology and the future",
            "visual_style": design.VISUAL_STYLES[visual_style],
            "empty_area": layout.empty_area,
            "color_scheme.mood": scheme.mood,
        },
    )


class FalFlux:
    """https://fal.ai/models/fal-ai/flux/schnell — synchronous endpoint, about US$0.003 per 1024² image."""

    def __init__(
        self,
        api_key: str,
        model: str = "fal-ai/flux/schnell",
        timeout_seconds: int = 90,
        blend_model: str = "fal-ai/flux/dev/image-to-image",
        blend_strength: float = 0.82,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout_seconds
        self.blend_model = blend_model
        self.blend_strength = blend_strength

    def generate(self, prompt: str) -> bytes:
        return self._run(
            self.model,
            {
                "prompt": prompt,
                "image_size": {"width": IMAGE_SIZE, "height": IMAGE_SIZE},
                "num_inference_steps": 4,
            },
        )

    def blend(self, prompt: str, photo: bytes) -> bytes:
        """Image-to-image on a real photo (JPEG bytes). The output keeps the photo's size (1080²)."""
        return self._run(
            self.blend_model,
            {
                "prompt": prompt,
                "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode("ascii"),
                "strength": self.blend_strength,
                "num_inference_steps": 28,
            },
        )

    def _run(self, model: str, body: dict) -> bytes:
        body = {
            **body,
            "num_images": 1,
            "enable_safety_checker": True,
            "output_format": "png",
            "sync_mode": True,  # return the image inline instead of a temporary CDN link
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"https://fal.run/{model}", json=body, headers={"Authorization": f"Key {self.api_key}"}
                )
                if resp.status_code >= 400:
                    raise AIError(f"圖片生成失敗（fal {resp.status_code}）：{resp.text[:300]}")
                images = resp.json().get("images") or []
                if not images or not images[0].get("url"):
                    raise AIError("圖片生成沒有回傳圖片")
                return _decode(images[0]["url"], client)
        except httpx.HTTPError as exc:
            raise AIError(f"圖片生成失敗：{exc}") from exc


class FluxImageAI:
    """AIService: copy from the text model (RAP or mock), card background from fal.

    With no fal backend (no FAL_API_KEY) the background is a plain gradient in the post's colors.
    """

    def __init__(self, text, backend: FalFlux | None) -> None:
        self.text = text  # RapAI or MockAI
        self.backend = backend

    def candidates(self, goal, tone):
        return self.text.candidates(goal, tone)

    def captions(self, goal, tone, audience, candidate, mode=None, on_text=None, reference=None, language="zh"):
        return self.text.captions(goal, tone, audience, candidate, mode, on_text, reference, language)

    def adjust(self, body, language="zh"):
        return self.text.adjust(body, language)

    def card_texts(self, candidate, layout, scheme, language="zh"):
        return self.text.card_texts(candidate, layout, scheme, language)

    def image(self, candidate, visual_style, layout, scheme):
        if self.backend is None:
            return gradient_png(scheme.primary, scheme.accent, size=design.CANVAS_SIZE)
        scene = self.text.scene(candidate, visual_style)
        return self.backend.generate(prompt_flux(scene, visual_style, layout, scheme))

    def blend(self, candidate, visual_style, layout, scheme, photo: bytes) -> bytes | None:
        """None when there is no image model: the caller then uses the photo as it is."""
        if self.backend is None:
            return None
        scene = self.text.scene(candidate, visual_style)
        return self.backend.blend(prompt_blend(scene, visual_style, layout, scheme), photo)


def _decode(ref: str, client: httpx.Client) -> bytes:
    """Image reference → bytes. Accepts a data URI, an https URL, or bare base64."""
    if ref.startswith("data:"):
        return base64.b64decode(ref.split(",", 1)[1])
    if ref.startswith("http"):
        resp = client.get(ref)
        resp.raise_for_status()
        return resp.content
    return base64.b64decode(ref)
