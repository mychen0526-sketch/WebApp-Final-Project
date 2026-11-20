"""Posts: CRUD + every status transition. Status changes only happen here (or in background jobs)."""
import asyncio
import json
import time

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..auth import get_current_user, get_services
from ..container import Services
from ..errors import Conflict, NotFound, Unprocessable
from ..schemas import (
    LANGUAGES,
    STATUS_VALUES,
    AdjustIn,
    ApproveIn,
    FeedbackIn,
    PostCreate,
    PostPatch,
    RegenerateIn,
    ScheduleIn,
    SubmitIn,
)
from ..services import design, safety
from ..services.ai import AIError
from ..services.generation import run_generation
from ..services.publishing import caption_for, publish_post
from ..services.storage import image_path
from ..state import Status, allowed_from, require
from ..timeutil import now_iso, parse_ts, utcnow
from .candidates import GenerationFailed
from .settings import load_settings
from .templates import get_owned_template

router = APIRouter(prefix="/api/posts", tags=["posts"])

THREADS_MAX_CHARS = 500
INSTAGRAM_MAX_CHARS = 2200
LINKEDIN_MAX_CHARS = 3000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg"}
STREAM_LIMIT_SECONDS = 10 * 60


# ---------------------------------------------------------------- helpers
def _get(services: Services, user_id: str, post_id: str) -> dict:
    post = services.repo.get_post(user_id, post_id)
    if not post:
        raise NotFound("找不到這篇貼文")
    return post


def _detail(services: Services, post: dict) -> dict:
    return {
        **post,
        "images": services.repo.list_images(post["id"]),
        "publications": services.repo.list_publications(post["id"]),
    }


def _transition(services: Services, user_id: str, post: dict, action: str, changes: dict) -> dict:
    """Compare-and-set: apply `changes` only if the status is still the one we just checked with
    `require`. A concurrent request that changed it first makes this return 409."""
    updated = services.repo.update_post(user_id, post["id"], changes, expected={post["status"]})
    if not updated:
        raise Conflict("貼文狀態已被其他操作改變，請重新整理", detail={"action": action})
    return updated


def _with_template(services: Services, user_id: str, choice: dict, template_id: str | None) -> dict:
    """Attach the user's template (checked for ownership now, so a bad id is a 404 and not a
    generation failure). Its URL travels with the choice because the template may be deleted later."""
    if template_id:
        template = get_owned_template(services, user_id, template_id)
        choice.update(
            template_id=template["id"],
            template_url=template["public_url"],
            template_path=template["storage_path"],
        )
    return choice


def post_language(post: dict) -> str:
    """The copy language chosen when the post was made (kept in canvas_json; older posts are zh)."""
    language = (post.get("canvas_json") or {}).get("language")
    return language if language in LANGUAGES else "zh"


def _design_from(services: Services, user_id: str, post: dict, body) -> dict:
    canvas = post.get("canvas_json") or {}
    # explicit null drops the news picture; leaving the field out keeps the previous one
    if "reference" in body.model_fields_set:
        reference = body.reference.model_dump() if body.reference else None
    else:
        reference = canvas.get("reference")
    image_mode = body.image_mode or (canvas.get("image_mode") if canvas.get("image_mode") in ("photo", "blend") else None)
    choice = design.resolve(
        body.layout or canvas.get("layout"),
        body.style if body.style is not None else canvas.get("style"),
        body.visual_style or canvas.get("visual_style"),
        image_mode,
        reference,
    )
    choice["language"] = body.language or post_language(post)
    if "template_id" in body.model_fields_set:  # explicit null drops the template
        return _with_template(services, user_id, choice, body.template_id)
    if canvas.get("template_id"):  # keep the previous template, even if it was removed from the picker
        choice.update(template_id=canvas["template_id"], template_url=canvas["image"]["url"],
                      template_path=canvas.get("template_path"))
    return choice


def _assert_safe(services: Services, user_id: str, post: dict) -> None:
    words = load_settings(services, user_id)["sensitive_words"]
    result = safety.scan(safety.post_text(post), words)
    if not result["ok"]:
        raise Unprocessable(
            f"安全檢查未通過，偵測到敏感詞：{'、'.join(result['detected'])}",
            detail=result,
            code="sensitive_content",
        )


def _account_problems(services: Services, user_id: str, platforms: list[str]) -> list[str]:
    problems = []
    for platform in platforms:
        account = services.repo.get_account(user_id, platform)
        if not account:
            problems.append(f"{platform} 尚未綁定帳號")
            continue
        expires = parse_ts(account.get("token_expires_at"))
        if expires and expires <= utcnow():
            problems.append(f"{platform} 帳號授權已過期，請重新連結")
    return problems


# ---------------------------------------------------------------- create / read
@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_post(
    body: PostCreate,
    background: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """P3 → P4: create the post in `generating` and generate copy + card in the background."""
    reference = body.reference.model_dump() if body.reference else None
    choice = design.resolve(body.layout, body.style, body.visual_style, body.image_mode, reference)
    choice["language"] = body.language or "zh"
    choice = _with_template(services, user_id, choice, body.template_id)
    candidates = body.candidates or [body.selected]
    post = services.repo.create_post(
        {
            "user_id": user_id,
            "goal": body.goal,
            "tone": body.tone,
            "audience": body.audience,
            "title": body.selected.title,
            "prompt_candidates": [c.model_dump() for c in candidates],
            "selected_prompt": body.selected.model_dump(),
            "status": Status.GENERATING.value,
        }
    )
    token = services.progress.start(post["id"])
    background.add_task(run_generation, services, user_id, post["id"], choice, None, token)
    return _detail(services, post)


@router.get("")
def list_posts(
    status_filter: str | None = Query(default=None, alias="status"),
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    if status_filter and status_filter not in STATUS_VALUES:
        raise Unprocessable(f"未知的狀態：{status_filter}", detail={"allowed": STATUS_VALUES})
    return services.repo.list_posts(user_id, status_filter)


@router.get("/{post_id}")
def get_post(post_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    return _detail(services, _get(services, user_id, post_id))


# ---------------------------------------------------------------- editing
@router.post("/{post_id}/generate", status_code=status.HTTP_202_ACCEPTED)
def regenerate(
    post_id: str,
    body: RegenerateIn,
    background: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """Regenerate copy + card (from editing or generation_failed). Optionally switch direction or style."""
    post = _get(services, user_id, post_id)
    require(post, "regenerate")
    changes: dict = {"status": Status.GENERATING.value, "generation_error": None}
    if body.selected:
        changes["selected_prompt"] = body.selected.model_dump()
    choice = _design_from(services, user_id, post, body)
    updated = _transition(services, user_id, post, "regenerate", changes)
    token = services.progress.start(post_id)
    background.add_task(run_generation, services, user_id, post_id, choice, body.mode, token)
    return _detail(services, updated)


@router.post("/{post_id}/cancel")
def cancel(post_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """「停止」: leave `generating` right away. With an earlier version (a rewrite) the post goes back
    to editing unchanged; a first generation has nothing to go back to, so it ends as generation_failed.
    The background task notices at its next step and stops without writing."""
    post = _get(services, user_id, post_id)
    require(post, "cancel")
    if post.get("caption_threads"):
        changes = {"status": Status.EDITING.value, "generation_error": None}
    else:
        changes = {"status": Status.GENERATION_FAILED.value, "generation_error": "已停止生成"}
    updated = _transition(services, user_id, post, "cancel", changes)
    services.progress.cancel(post_id)
    return _detail(services, updated)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/{post_id}/stream")
async def stream(post_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """Server-sent events while a post generates.

    `progress` {stage, threads}: stage is copy → card → image → save; threads is the Threads caption so far.
    `done` {post}: the post once it has left `generating` (editing, generation_failed, …). Then the stream ends.
    """
    await run_in_threadpool(_get, services, user_id, post_id)
    hub = services.progress

    async def events():
        last = -1
        started = time.monotonic()
        tick = 0
        while time.monotonic() - started < STREAM_LIMIT_SECONDS:
            item = hub.get(post_id)
            if item and item.version != last and not (item.done or item.cancelled):
                last = item.version
                yield _sse("progress", {"stage": item.stage, "threads": item.threads})
            settled = item is not None and (item.done or item.cancelled)
            # no live entry (another worker / restart): fall back to checking the database every ~2 s
            if settled or tick % 13 == 0:
                post = await run_in_threadpool(services.repo.get_post, user_id, post_id)
                if not post or post["status"] != Status.GENERATING:
                    detail = await run_in_threadpool(_detail, services, post) if post else None
                    yield _sse("done", {"post": detail})
                    return
            if tick % 100 == 99:
                yield ": ping\n\n"  # keep proxies from closing an idle connection
            tick += 1
            await asyncio.sleep(0.15)
        yield _sse("timeout", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{post_id}/adjust")
def adjust(
    post_id: str,
    body: AdjustIn,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """AI 微調: one chat turn. Returns {reply, ...changed fields}; nothing is saved until the editor saves."""
    post = _get(services, user_id, post_id)
    if post["status"] != Status.EDITING:
        raise Conflict("只有草稿可以微調，請先退回修改", detail={"status": post["status"], "action": "adjust"})
    try:
        result = services.ai.adjust(body, post_language(post))
    except AIError as exc:
        raise GenerationFailed(str(exc)) from exc
    return result.model_dump(exclude_none=True)


@router.patch("/{post_id}")
def save_post(
    post_id: str,
    body: PostPatch,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """Save editor content. Editing an approved post sends it back to editing (must be reviewed again, E4)."""
    post = _get(services, user_id, post_id)
    require(post, "save")
    changes = body.model_dump(exclude_unset=True)
    if post["status"] == Status.APPROVED:
        changes.update(status=Status.EDITING.value, approved_at=None)
    return _detail(services, _transition(services, user_id, post, "save", changes))


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(post_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    post = _get(services, user_id, post_id)
    require(post, "delete")
    if not services.repo.delete_post(user_id, post_id, allowed_from("delete")):
        raise Conflict("貼文狀態已被其他操作改變，請重新整理")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{post_id}/images", status_code=status.HTTP_201_CREATED)
async def upload_image(
    post_id: str,
    file: UploadFile = File(...),
    source: str = Form("uploaded"),
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """Store an image. `uploaded` replaces a picture while editing; `exported` is the canvas PNG that
    will actually be published, so it is also accepted while the post is locked for review."""
    post = _get(services, user_id, post_id)
    allowed = {
        "uploaded": {Status.EDITING},
        "exported": {Status.EDITING, Status.PENDING_REVIEW, Status.APPROVED},
    }
    if source not in allowed:
        raise Unprocessable("source 只能是 uploaded 或 exported")
    if post["status"] not in allowed[source]:
        raise Conflict(f"目前狀態「{post['status']}」不能上傳 {source} 圖片")
    ext = IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise Unprocessable("只接受 PNG 或 JPEG 圖片")
    data = await file.read()
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise Unprocessable("圖片大小需介於 1 byte 到 8 MB")
    path = image_path(user_id, post_id, ext)
    url = services.storage.upload(path, data, file.content_type)
    return services.repo.add_image(post_id, source, path, url)


@router.post("/{post_id}/feedback", status_code=status.HTTP_201_CREATED)
def feedback(
    post_id: str,
    body: FeedbackIn,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    _get(services, user_id, post_id)
    return services.repo.add_feedback(user_id, post_id, body.rating)


# ---------------------------------------------------------------- review
@router.post("/{post_id}/submit")
def submit(
    post_id: str,
    body: SubmitIn,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """editing → pending_review with the platforms to publish to. Checks platform limits (E7, E8)."""
    post = _get(services, user_id, post_id)
    require(post, "submit")
    problems = _account_problems(services, user_id, body.platforms)
    threads_caption = post.get("caption_threads") or ""
    ig_caption = post.get("caption_instagram") or ""
    linkedin_caption = caption_for(post, "linkedin")
    images = services.repo.list_images(post_id)
    if "threads" in body.platforms:
        if len(threads_caption) > THREADS_MAX_CHARS:
            problems.append(f"Threads 文案 {len(threads_caption)} 字，超過上限 {THREADS_MAX_CHARS}")
        if not threads_caption.strip() and not images:
            problems.append("Threads 貼文需要文字或圖片")
    if "instagram" in body.platforms:
        if len(ig_caption) > INSTAGRAM_MAX_CHARS:
            problems.append(f"Instagram 文案 {len(ig_caption)} 字，超過上限 {INSTAGRAM_MAX_CHARS}")
        if not images:
            problems.append("Instagram 貼文一定要有圖片")
    if "linkedin" in body.platforms:
        if len(linkedin_caption) > LINKEDIN_MAX_CHARS:
            problems.append(f"LinkedIn 文案 {len(linkedin_caption)} 字，超過上限 {LINKEDIN_MAX_CHARS}")
        if not linkedin_caption.strip() and not images:
            problems.append("LinkedIn 貼文需要文字或圖片")
    if problems:
        raise Unprocessable("還不能送審：" + "；".join(problems), detail={"problems": problems}, code="submit_blocked")
    updated = _transition(
        services, user_id, post, "submit", {"status": Status.PENDING_REVIEW.value, "platforms": body.platforms}
    )
    return _detail(services, updated)


@router.post("/{post_id}/reject")
def reject(post_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """pending_review / approved → editing."""
    post = _get(services, user_id, post_id)
    require(post, "reject")
    updated = _transition(services, user_id, post, "reject", {"status": Status.EDITING.value, "approved_at": None})
    return _detail(services, updated)


# README path name for the same action
router.add_api_route("/{post_id}/return", reject, methods=["POST"], include_in_schema=False)


@router.post("/{post_id}/approve")
def approve(
    post_id: str,
    body: ApproveIn,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """pending_review → approved. The person must confirm they read it all and hold the rights."""
    post = _get(services, user_id, post_id)
    require(post, "approve")
    if not (body.read_confirmed and body.rights_confirmed):
        raise Unprocessable("核准前需勾選「已讀過全文」與「有使用權利」", code="confirmation_required")
    updated = _transition(services, user_id, post, "approve", {"status": Status.APPROVED.value, "approved_at": now_iso()})
    return _detail(services, updated)


# ---------------------------------------------------------------- publish
@router.post("/{post_id}/publish", status_code=status.HTTP_202_ACCEPTED)
def publish(
    post_id: str,
    background: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """approved → publishing → published / partially_published / publish_failed.
    Non-approved posts get 409 (E3); a second click gets 409 because the status is already publishing (E5)."""
    post = _get(services, user_id, post_id)
    require(post, "publish")
    _assert_safe(services, user_id, post)
    updated = _transition(services, user_id, post, "publish", {"status": Status.PUBLISHING.value})
    background.add_task(publish_post, services, updated)
    return _detail(services, updated)


@router.post("/{post_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(
    post_id: str,
    background: BackgroundTasks,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """Retry only the platforms that did not succeed (E6, E9)."""
    post = _get(services, user_id, post_id)
    require(post, "retry")
    succeeded = {p["platform"] for p in services.repo.list_publications(post_id) if p["status"] == "success"}
    targets = [p for p in post.get("platforms") or [] if p not in succeeded]
    updated = _transition(services, user_id, post, "retry", {"status": Status.PUBLISHING.value})
    background.add_task(publish_post, services, updated, targets)
    return _detail(services, updated)


@router.post("/{post_id}/schedule")
def schedule(
    post_id: str,
    body: ScheduleIn,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """approved → scheduled. The scheduler publishes it when due."""
    post = _get(services, user_id, post_id)
    require(post, "schedule")
    if body.when <= utcnow():
        raise Unprocessable("排程時間必須在未來", code="schedule_in_past")
    _assert_safe(services, user_id, post)
    updated = _transition(
        services, user_id, post, "schedule", {"status": Status.SCHEDULED.value, "scheduled_at": body.when.isoformat()}
    )
    return _detail(services, updated)


@router.post("/{post_id}/cancel-schedule")
def cancel_schedule(post_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """scheduled → approved; clears the time. Not a delete."""
    post = _get(services, user_id, post_id)
    require(post, "cancel_schedule")
    updated = _transition(
        services, user_id, post, "cancel_schedule", {"status": Status.APPROVED.value, "scheduled_at": None}
    )
    return _detail(services, updated)


@router.post("/{post_id}/reopen")
def reopen(post_id: str, user_id: str = Depends(get_current_user), services: Services = Depends(get_services)):
    """publish_failed → editing, to fix the content; it must be reviewed again."""
    post = _get(services, user_id, post_id)
    require(post, "reopen")
    updated = _transition(services, user_id, post, "reopen", {"status": Status.EDITING.value, "approved_at": None})
    return _detail(services, updated)
