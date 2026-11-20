"""趨勢情報: search news / trend reports with their real lead pictures. Stateless.

The frontend shows the results; when the user picks one, the article (and optionally its
picture) travels in POST /api/posts as `reference`, and generation uses it as a fact source
and a card background (see services/generation.py).
"""
from fastapi import APIRouter, Depends

from ..auth import get_current_user, get_services
from ..container import Services
from ..errors import ServiceUnavailable
from ..schemas import ResearchIn
from ..services.research import ResearchError
from .candidates import GenerationFailed

router = APIRouter(prefix="/api", tags=["research"])


class SearchFailed(GenerationFailed):
    code = "search_failed"


@router.post("/research")
def research(body: ResearchIn, _: str = Depends(get_current_user), services: Services = Depends(get_services)):
    if services.research is None:
        raise ServiceUnavailable("伺服器已關閉新聞搜尋（SEARCH_BACKEND=off）")
    try:
        results = services.research.search(body.query, body.limit)
    except ResearchError as exc:
        raise SearchFailed(str(exc)) from exc
    return {
        "backend": services.research.name,
        "results": [r.model_dump() for r in results],
        "with_images": sum(1 for r in results if r.image_url),
    }
