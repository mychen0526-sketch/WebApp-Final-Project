"""Card layouts and color schemes for the 1080x1080 canvas.

Color schemes follow the frontend's STYLES (frontend/src/studio.js) so `style` 0–3 means the same
thing on both sides. Layout coordinates are canvas pixels; `empty_area` tells the image prompt (C)
which part of the picture to keep clean for text.
"""
from dataclasses import dataclass

CANVAS_SIZE = 1080


@dataclass(frozen=True)
class Layout:
    name: str
    alignment: str
    empty_area: str
    headline: tuple[int, int]
    highlight: tuple[int, int]
    desc: tuple[int, int]


@dataclass(frozen=True)
class ColorScheme:
    name: str
    primary: str
    accent: str
    mood: str
    headline: str
    highlight: str
    description: str


LAYOUTS: dict[str, Layout] = {
    "top": Layout("top", "center", "top third", (540, 120), (540, 230), (540, 310)),
    "bottom": Layout("bottom", "center", "bottom third", (540, 760), (540, 870), (540, 950)),
    "center": Layout("center", "center", "top and bottom bands", (540, 110), (540, 210), (540, 970)),
    "left": Layout("left", "left", "left half", (80, 380), (80, 500), (80, 580)),
}

COLOR_SCHEMES: list[ColorScheme] = [
    ColorScheme("科技深藍", "#31406a", "#8d84d6", "deep navy and soft violet, calm and trustworthy", "#FFFFFF", "#C9C3FF", "#E4E7F2"),
    ColorScheme("薄荷科技", "#35524f", "#7eb8b0", "dark teal with mint highlights, fresh and clean", "#FFFFFF", "#BFE6E0", "#E2F1EE"),
    ColorScheme("未來粉紫", "#7a4d6c", "#e3b7c6", "plum and blush pink, futuristic and warm", "#FFFFFF", "#F6D3DF", "#F3E6EC"),
    ColorScheme("精品暖金", "#4a4032", "#d4bc90", "dark bronze with warm gold, premium and refined", "#FFFFFF", "#EBD9B4", "#F1EADC"),
]

VISUAL_STYLES: dict[str, str] = {
    "abstract": "abstract technology visual, flowing light lines and data streams, depth of field",
    "isometric": "clean isometric 3D illustration of a concept, soft shadows, minimal objects",
    "geometric": "minimal geometric shapes and gradients, flat design, bold composition",
    "editorial": "editorial illustration style, conceptual metaphor, muted palette",
}

DEFAULT_LAYOUT = "top"
DEFAULT_STYLE = 0
DEFAULT_VISUAL_STYLE = "abstract"


def resolve(
    layout: str | None,
    style: int | None,
    visual_style: str | None,
    image_mode: str | None = None,
    reference: dict | None = None,
) -> dict:
    """Return the design choice as a JSON-able dict (stored in canvas_json)."""
    return {
        "layout": layout or DEFAULT_LAYOUT,
        "style": DEFAULT_STYLE if style is None else style,
        "visual_style": visual_style or DEFAULT_VISUAL_STYLE,
        # a real picture is only used when there is a reference to take it from
        "image_mode": (image_mode or "photo") if reference else "ai",
        "reference": reference,
    }


def layout_vars(layout: Layout) -> dict[str, str]:
    return {
        "layout.name": layout.name,
        "layout.alignment": layout.alignment,
        "layout.headline.x": str(layout.headline[0]),
        "layout.headline.y": str(layout.headline[1]),
        "layout.highlight.x": str(layout.highlight[0]),
        "layout.highlight.y": str(layout.highlight[1]),
        "layout.desc.x": str(layout.desc[0]),
        "layout.desc.y": str(layout.desc[1]),
        "empty_area": layout.empty_area,
    }


def scheme_vars(scheme: ColorScheme) -> dict[str, str]:
    return {
        "color_scheme.name": scheme.name,
        "color_scheme.mood": scheme.mood,
        "color_scheme.headline": scheme.headline,
        "color_scheme.highlight": scheme.highlight,
        "color_scheme.description": scheme.description,
    }
