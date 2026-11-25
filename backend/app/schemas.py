"""Request and AI-output models."""
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .state import Status

Platform = Literal["threads", "instagram", "linkedin"]
PLATFORMS: tuple[str, ...] = ("threads", "instagram", "linkedin")
ImageSource = Literal["generated", "uploaded", "exported", "template", "reference"]
LayoutName = Literal["top", "bottom", "center", "left"]
VisualStyle = Literal["abstract", "isometric", "geometric", "editorial"]
# How a real (news) picture found by search is used on the card:
#   photo — the photo itself is the background (credited on the card)
#   blend — FLUX image-to-image restyles the photo into the post's look (keeps its composition)
ImageMode = Literal["ai", "photo", "blend"]
# Language of the generated copy and card text: 繁體中文 / English / 中英雙語 (Chinese first).
Language = Literal["zh", "en", "both"]
LANGUAGES: tuple[str, ...] = ("zh", "en", "both")


def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("不能是空白")
    return value


# ---------- AI outputs (validated before they are stored) ----------
class Candidate(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    angle: str = Field(min_length=1, max_length=200)
    hook: str = Field(min_length=1, max_length=120)


class Captions(BaseModel):
    threads: str = Field(min_length=1)
    instagram: str = Field(min_length=1)
    linkedin: str = ""  # filled from the IG copy when the model leaves it out (see generation)


class Adjustment(BaseModel):
    """AI 微調 reply: only the fields the model changed are set."""

    reply: str = Field(min_length=1, max_length=300)
    title: str | None = Field(default=None, max_length=60)
    subtitle: str | None = Field(default=None, max_length=60)
    threads: str | None = Field(default=None, max_length=5000)
    instagram: str | None = Field(default=None, max_length=5000)
    linkedin: str | None = Field(default=None, max_length=5000)
    style: int | None = Field(default=None, ge=0, le=3)
    font: int | None = Field(default=None, ge=24, le=44)


class Position(BaseModel):
    x: float
    y: float


class TextElement(BaseModel):
    type: Literal["text"] = "text"
    textType: Literal["headline", "highlight", "description"]
    text: str = Field(min_length=1, max_length=60)
    position: Position
    fontSize: int
    fontFamily: str
    fontWeight: str
    color: str
    alignment: Literal["left", "center", "right"]


class Reference(BaseModel):
    """A news / trend article found by search, optionally with its lead picture."""

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="", max_length=120)  # publisher name, shown as the photo credit
    published: str | None = Field(default=None, max_length=60)
    summary: str = Field(default="", max_length=1500)
    image_url: str | None = Field(default=None, max_length=2000)

    @field_validator("url", "image_url")
    @classmethod
    def _http(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("只接受 http(s) 網址")
        return value


class ResearchIn(BaseModel):
    query: str = Field(max_length=200)
    limit: int = Field(default=8, ge=1, le=12)

    _query = field_validator("query")(_strip_required)


# ---------- Requests ----------
class CandidatesIn(BaseModel):
    goal: str = Field(max_length=2000)
    tone: str | None = Field(default=None, max_length=50)

    _goal = field_validator("goal")(_strip_required)


class DesignOptions(BaseModel):
    layout: LayoutName | None = None
    style: int | None = Field(default=None, ge=0, le=3)
    visual_style: VisualStyle | None = None
    # A user's own background template (GET /api/templates). When set, the AI image step is
    # skipped and the template is used as the card background. Send null to drop it on regenerate.
    template_id: str | None = Field(default=None, max_length=64)
    # A real picture from search (Reference.image_url) and how to use it. Ignored with a template.
    image_mode: ImageMode | None = None
    reference: Reference | None = None
    # Leave out to keep the post's language on regenerate (new posts default to zh).
    language: Language | None = None


class PostCreate(DesignOptions):
    goal: str = Field(max_length=2000)
    tone: str | None = Field(default=None, max_length=50)
    audience: str | None = Field(default=None, max_length=100)
    candidates: list[Candidate] = Field(default_factory=list, max_length=6)
    selected: Candidate

    _goal = field_validator("goal")(_strip_required)


class RegenerateIn(DesignOptions):
    selected: Candidate | None = None
    mode: Literal["short", "friendly", "new"] | None = None


class AdjustTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=1000)


class AdjustCurrent(BaseModel):
    """What the editor shows right now (may be unsaved)."""

    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=200)
    threads: str = Field(default="", max_length=5000)
    instagram: str = Field(default="", max_length=5000)
    linkedin: str = Field(default="", max_length=5000)
    style: int = Field(default=0, ge=0, le=3)
    font: int = Field(default=30, ge=12, le=60)
    palettes: list[str] = Field(default_factory=list, max_length=4)


class AdjustIn(BaseModel):
    instruction: str = Field(max_length=500)
    current: AdjustCurrent
    history: list[AdjustTurn] = Field(default_factory=list, max_length=12)

    _instruction = field_validator("instruction")(_strip_required)


MAX_CANVAS_BYTES = 64 * 1024


class PostPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    caption_threads: str | None = Field(default=None, max_length=5000)
    caption_instagram: str | None = Field(default=None, max_length=5000)
    caption_linkedin: str | None = Field(default=None, max_length=5000)
    canvas_json: dict | None = None
    tone: str | None = Field(default=None, max_length=50)
    audience: str | None = Field(default=None, max_length=100)

    @field_validator("canvas_json")
    @classmethod
    def _canvas_size(cls, value: dict | None) -> dict | None:
        # the editor's layout (texts, positions, colours) is a few KB; anything bigger is not a canvas
        if value is not None and len(json.dumps(value, ensure_ascii=False, default=str).encode()) > MAX_CANVAS_BYTES:
            raise ValueError(f"canvas_json 不能超過 {MAX_CANVAS_BYTES // 1024} KB")
        return value


class SubmitIn(BaseModel):
    platforms: list[Platform] = Field(min_length=1)

    @field_validator("platforms")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class RetryIn(BaseModel):
    """Platforms whose previous attempt is "uncertain" (may be live) and that the user checked on
    the platform and confirms did NOT go out. Only needed where the backend cannot search (LinkedIn)."""

    confirm_unpublished: list[Platform] = Field(default_factory=list)


class ApproveIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    read_confirmed: bool = Field(default=False, alias="readConfirmed")
    rights_confirmed: bool = Field(default=False, alias="rightsConfirmed")


class ScheduleIn(BaseModel):
    when: datetime

    @field_validator("when")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("時間需要包含時區，例如 2026-12-01T09:00:00+08:00")
        return value


class FeedbackIn(BaseModel):
    rating: Literal["like", "neutral", "dislike"]


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str | None = Field(default=None, max_length=100)
    default_tone: str | None = Field(default=None, max_length=50)
    default_audience: str | None = Field(default=None, max_length=100)
    sensitive_words: list[str] | None = Field(default=None, max_length=200)
    # 偏好設定 → 預設發布目的地
    default_platforms: list[Platform] | None = None

    @field_validator("default_platforms")
    @classmethod
    def _dedupe_platforms(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else list(dict.fromkeys(value))

    @field_validator("sensitive_words")
    @classmethod
    def _clean_words(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(w.strip() for w in value if w and w.strip()))


class ScanIn(BaseModel):
    title: str = ""
    text: str = ""


STATUS_VALUES = [s.value for s in Status]
