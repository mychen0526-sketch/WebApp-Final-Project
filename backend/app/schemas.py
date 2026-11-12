"""Request and AI-output models."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .state import Status

Platform = Literal["threads", "instagram"]
PLATFORMS: tuple[str, ...] = ("threads", "instagram")
ImageSource = Literal["generated", "uploaded", "exported"]
LayoutName = Literal["top", "bottom", "center", "left"]
VisualStyle = Literal["abstract", "isometric", "geometric", "editorial"]


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


# ---------- Requests ----------
class CandidatesIn(BaseModel):
    goal: str = Field(max_length=2000)
    tone: str | None = Field(default=None, max_length=50)

    _goal = field_validator("goal")(_strip_required)


class DesignOptions(BaseModel):
    layout: LayoutName | None = None
    style: int | None = Field(default=None, ge=0, le=3)
    visual_style: VisualStyle | None = None


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


class PostPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    caption_threads: str | None = Field(default=None, max_length=5000)
    caption_instagram: str | None = Field(default=None, max_length=5000)
    canvas_json: dict | None = None
    tone: str | None = Field(default=None, max_length=50)
    audience: str | None = Field(default=None, max_length=100)


class SubmitIn(BaseModel):
    platforms: list[Platform] = Field(min_length=1)

    @field_validator("platforms")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


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
