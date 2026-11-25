"""User settings (brand, default tone/audience/platforms, sensitive words), recent feedback and
the safety scan endpoint."""
from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user, get_services
from ..container import Services
from ..schemas import ScanIn, SettingsIn
from ..services import safety

router = APIRouter(prefix="/api", tags=["settings"])

DEFAULTS = {
    "brand_name": "",
    "default_tone": "專業分析",
    "default_audience": "創業者與科技從業者",
    "sensitive_words": safety.DEFAULT_SENSITIVE_WORDS,
    "default_platforms": [],
}


def load_settings(services: Services, user_id: str) -> dict:
    row = services.repo.get_settings(user_id) or {}
    merged = {**DEFAULTS, **{k: v for k, v in row.items() if v is not None}}
    merged["user_id"] = user_id
    return merged


@router.get("/settings")
def get_settings(user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    return load_settings(services, user_id)


@router.put("/settings")
def put_settings(body: SettingsIn, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    services.repo.upsert_settings(user_id, body.model_dump(exclude_unset=True))
    return load_settings(services, user_id)


@router.get("/feedback")
def recent_feedback(
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """偏好設定「最近的回饋」: newest first, with the post title."""
    return services.repo.list_feedback(user_id, limit)


@router.post("/safety/scan")
def scan(body: ScanIn, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """Check text for the user's sensitive words (blocking) and absolute claims (warning only)."""
    words = load_settings(services, user_id)["sensitive_words"]
    return safety.scan(f"{body.title}\n{body.text}", words)
