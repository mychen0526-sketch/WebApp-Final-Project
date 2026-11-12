"""P3: prompt candidates. Stateless; nothing is saved until the user picks one (POST /api/posts)."""
from fastapi import APIRouter, Depends

from ..auth import get_current_user, get_services
from ..container import Services
from ..errors import AppError
from ..schemas import CandidatesIn
from ..services.ai import AIError

router = APIRouter(prefix="/api", tags=["generation"])


class GenerationFailed(AppError):
    status_code = 502
    code = "generation_failed"


@router.post("/candidates")
def candidates(body: CandidatesIn, _: str = Depends(get_current_user), services: Services = Depends(get_services)):
    try:
        result = services.ai.candidates(body.goal, body.tone)
    except AIError as exc:
        raise GenerationFailed(str(exc)) from exc
    return {"candidates": [c.model_dump() for c in result]}
