"""The user's own background templates (圖片模板). Uploaded once, then picked when creating or
regenerating a post: generation uses the template as the card background instead of an AI image."""
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from ..auth import get_current_user, get_services
from ..container import Services
from ..errors import NotFound, Unprocessable
from ..services.storage import template_path

router = APIRouter(prefix="/api/templates", tags=["templates"])

MAX_TEMPLATE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg"}
MAX_TEMPLATES = 50


def get_owned_template(services: Services, user_id: str, template_id: str) -> dict:
    row = services.repo.get_template(user_id, template_id)
    if not row:
        raise NotFound("找不到這個圖片模板")
    return row


@router.get("")
def list_templates(user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    return services.repo.list_templates(user_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_template(
    file: UploadFile = File(...),
    name: str = Form(""),
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """multipart: `file` (PNG/JPEG ≤ 8MB, 1:1 recommended — the card is 1080×1080), `name`."""
    ext = IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise Unprocessable("只接受 PNG 或 JPEG 圖片")
    data = await file.read()
    if not data or len(data) > MAX_TEMPLATE_BYTES:
        raise Unprocessable("圖片大小需介於 1 byte 到 8 MB")
    if len(services.repo.list_templates(user_id)) >= MAX_TEMPLATES:
        raise Unprocessable(f"最多只能存 {MAX_TEMPLATES} 個模板，請先刪除不用的")
    clean = name.strip()[:60] or (file.filename or "未命名模板").rsplit(".", 1)[0][:60]
    path = template_path(user_id, ext)
    url = services.storage.upload(path, data, file.content_type)
    return services.repo.add_template(user_id, {"name": clean, "storage_path": path, "public_url": url})


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """Removes it from the picker. The stored file is kept so posts that already use it still render."""
    get_owned_template(services, user_id, template_id)
    services.repo.delete_template(user_id, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
