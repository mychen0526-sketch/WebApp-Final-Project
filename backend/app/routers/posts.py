"""Posts: CRUD + every status transition. Status changes only happen here (or in background jobs)."""
import asyncio
import json
import time

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..auth import get_current_user, get_services
from ..container import Services
from ..jobs import dispatch
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
    RetryIn,
    ScheduleIn,
    SubmitIn,
)
from ..services import design, safety
from ..services.ai import AIError
from ..services.publishing import caption_for, unverifiable_uncertain
from ..services.storage import image_path
from ..services.uploads import read_image
from ..state import Status, allowed_from, require
from ..timeutil import now_iso, parse_ts, utcnow
from .candidates import GenerationFailed
from .settings import load_settings

router = APIRouter(prefix="/api/posts", tags=["posts"])

THREADS_MAX_CHARS = 500
INSTAGRAM_MAX_CHARS = 2200
LINKEDIN_MAX_CHARS = 3000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
STREAM_LIMIT_SECONDS = 10 * 60
TEMPLATE_GONE = "這張模板已經刪除，改用 AI 底圖"


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
    """Attach the user's template, looked up in the database (only the user's own). Its URL travels
    with the choice because the template may be deleted later. A template that no longer exists (or
    belongs to someone else) does not fail the post: it is generated with an AI background and
    `template_note` says why (shown as canvas_json.image_note and in the response's `notices`)."""
    if template_id:
        template = services.repo.get_template(user_id, template_id)
        if template:
            choice.update(
                template_id=template["id"],
                template_url=template["public_url"],
                template_path=template["storage_path"],
            )
        else:
            choice["template_note"] = TEMPLATE_GONE
    return choice


def _post_template_image(services: Services, post_id: str) -> dict | None:
    """The template background this post was generated with (written by the server, so trusted)."""
    rows = [i for i in services.repo.list_images(post_id) if i["source"] == "template"]
    return max(rows, key=lambda i: i["created_at"]) if rows else None


def _notices(choice: dict) -> list[str]:
    return [choice["template_note"]] if choice.get("template_note") else []


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
    if canvas.get("template_id"):
        # Keep the previous template, even if it was removed from the picker. canvas_json is
        # written by the client, so its URL / storage path are never used: the template comes from
        # the database, or else from the template image the server stored for this post.
        template = services.repo.get_template(user_id, str(canvas["template_id"]))
        if template:
            choice.update(template_id=template["id"], template_url=template["public_url"],
                          template_path=template["storage_path"])
        elif stored := _post_template_image(services, post["id"]):
            choice.update(template_id=str(canvas["template_id"]), template_url=stored["public_url"],
                          template_path=stored["storage_path"])
        else:
            choice["template_note"] = TEMPLATE_GONE
    return choice


def _assert_safe(services: Services, user_id: str, post: dict) -> None:
    """Sensitive words block submit, approve, publish, schedule and retry (422 with the words)."""
    words = load_settings(services, user_id)["sensitive_words"]
    result = safety.scan(safety.post_text(post), words)
    if not result["ok"]:
        raise Unprocessable(
            f"安全檢查未通過，偵測到敏感詞：{'、'.join(result['detected'])}",
            detail=result,
            code="sensitive_content",
        )


PLATFORM_LABEL = {"threads": "Threads", "instagram": "Instagram", "linkedin": "LinkedIn"}


def _account_problems(services: Services, user_id: str, platforms: list[str]) -> list[str]:
    problems = []
    for platform in platforms:
        label = PLATFORM_LABEL.get(platform, platform)
        account = services.repo.get_account(user_id, platform)
        if not account:
            problems.append(f"{label} 尚未綁定帳號")
            continue
        if account.get("auth_error"):
            problems.append(f"{label} 帳號授權已失效（可能在平台上被撤銷），請重新連結")
            continue
        expires = parse_ts(account.get("token_expires_at"))
        if expires and expires <= utcnow():
            problems.append(f"{label} 帳號授權已過期，請重新連結")
    return problems


def _card_export_problem(services: Services, post: dict, images: list[dict]) -> str | None:
    """The card is published as the PNG the editor exports (background + text). Without a fresh
    export the platforms would get the bare background with none of the card text, or an older
    card from before the last edit, so submitting is blocked until the export succeeds."""
    canvas = post.get("canvas_json") or {}
    if not images or not canvas.get("texts"):
        return None
    exported = [i for i in images if i["source"] == "exported"]
    latest = max((parse_ts(i["created_at"]) for i in exported), default=None)
    saved = parse_ts(post.get("updated_at"))
    if latest is None:
        return "圖卡還沒有匯出成功，請重試送審（發布會用含文字的圖卡）"
    if saved and latest < saved:
        return "圖卡在最後一次修改後沒有重新匯出，請重試送審"
    return None


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
    dispatch(services, background, "generate", user_id=user_id, post_id=post["id"], choice=choice, mode=None)
    return {**_detail(services, post), "notices": _notices(choice)}


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
    dispatch(services, background, "generate", user_id=user_id, post_id=post_id, choice=choice, mode=body.mode)
    return {**_detail(services, updated), "notices": _notices(choice)}


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
    """Store an image. `uploaded` replaces a picture; `exported` is the canvas PNG that will actually
    be published (the editor uploads it right before submitting). Both only while editing: once a
    post is submitted the picture that will go out is locked, so it cannot be swapped after review
    without going back to editing (and through review again)."""
    post = _get(services, user_id, post_id)
    if source not in ("uploaded", "exported"):
        raise Unprocessable("source 只能是 uploaded 或 exported")
    if post["status"] != Status.EDITING:
        raise Conflict(
            f"目前狀態「{post['status']}」不能上傳圖片，待審核或已核准的貼文要先退回成草稿",
            detail={"status": post["status"], "action": "upload_image"},
        )
    data, content_type, ext = await read_image(file, MAX_UPLOAD_BYTES)
    path = image_path(user_id, post_id, ext)
    url = services.storage.upload(path, data, content_type)
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
    if export_problem := _card_export_problem(services, post, images):
        problems.append(export_problem)
    if problems:
        raise Unprocessable("還不能送審：" + "；".join(problems), detail={"problems": problems}, code="submit_blocked")
    _assert_safe(services, user_id, post)  # say which word it is now, not only when publishing
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
    _assert_safe(services, user_id, post)  # words may have been added to the list after submitting
    updated =_transition(services, user_id, post, "approve", {"status": Status.APPROVED.value, "approved_at": now_iso()})
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
    dispatch(services, background, "publish", user_id=user_id, post_id=post_id)
    return _detail(services, updated)


@router.post("/{post_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(
    post_id: str,
    background: BackgroundTasks,
    body: RetryIn | None = None,
    user_id: str = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    """Retry only the platforms that did not succeed (E6, E9).

    A platform whose last attempt is `uncertain` (request sent, no answer) may already show the post.
    Threads / Instagram are searched first and the found post is recorded instead of posting twice.
    LinkedIn cannot be searched with our scopes, so the retry is refused (409 `publish_uncertain`)
    until the user checks LinkedIn and sends {"confirm_unpublished": ["linkedin"]}."""
    post = _get(services, user_id, post_id)
    require(post, "retry")
    _assert_safe(services, user_id, post)
    confirmed = list((body.confirm_unpublished if body else []) or [])
    succeeded = {p["platform"] for p in services.repo.list_publications(post_id) if p["status"] == "success"}
    targets = [p for p in post.get("platforms") or [] if p not in succeeded]
    unverified = [p for p in unverifiable_uncertain(services, post_id, targets) if p not in confirmed]
    if unverified:
        names = "、".join(PLATFORM_LABEL.get(p, p) for p in unverified)
        raise Conflict(
            f"{names} 上一次發布沒有收到回應，貼文可能已經發出。請先到 {names} 確認；確定沒有發出再重試",
            detail={"platforms": unverified, "action": "retry"},
            code="publish_uncertain",
        )
    updated = _transition(services, user_id, post, "retry", {"status": Status.PUBLISHING.value})
    dispatch(services, background, "publish", user_id=user_id, post_id=post_id, targets=targets, confirmed=confirmed)
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
