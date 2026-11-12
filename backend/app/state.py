"""Post status machine. The backend is the only place that changes posts.status.

    generating → editing | generation_failed
    editing → generating (regenerate) | pending_review (submit)
    pending_review → editing (reject) | approved (approve)
    approved → editing (reject / edit) | publishing (publish) | scheduled (schedule)
    scheduled → approved (cancel) | publishing (scheduler)
    publishing → published | partially_published | publish_failed
    partially_published / publish_failed → publishing (retry)
    publish_failed → editing (reopen)
"""
from enum import StrEnum

from .errors import Conflict


class Status(StrEnum):
    GENERATING = "generating"
    GENERATION_FAILED = "generation_failed"
    EDITING = "editing"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PARTIALLY_PUBLISHED = "partially_published"
    PUBLISH_FAILED = "publish_failed"


S = Status

# action -> (allowed source statuses, target status or None when the action deletes the post)
TRANSITIONS: dict[str, tuple[frozenset[Status], Status | None]] = {
    "regenerate": (frozenset({S.EDITING, S.GENERATION_FAILED}), S.GENERATING),
    "save": (frozenset({S.EDITING, S.APPROVED}), S.EDITING),
    "delete": (frozenset({S.EDITING, S.GENERATION_FAILED}), None),
    "submit": (frozenset({S.EDITING}), S.PENDING_REVIEW),
    "reject": (frozenset({S.PENDING_REVIEW, S.APPROVED}), S.EDITING),
    "approve": (frozenset({S.PENDING_REVIEW}), S.APPROVED),
    "publish": (frozenset({S.APPROVED}), S.PUBLISHING),
    "retry": (frozenset({S.PARTIALLY_PUBLISHED, S.PUBLISH_FAILED}), S.PUBLISHING),
    "schedule": (frozenset({S.APPROVED}), S.SCHEDULED),
    "cancel_schedule": (frozenset({S.SCHEDULED}), S.APPROVED),
    "reopen": (frozenset({S.PUBLISH_FAILED}), S.EDITING),
}

ACTION_LABELS = {
    "regenerate": "重新生成",
    "save": "儲存編輯",
    "delete": "刪除",
    "submit": "送審",
    "reject": "退回修改",
    "approve": "核准",
    "publish": "發布",
    "retry": "重試發布",
    "schedule": "排程",
    "cancel_schedule": "取消排程",
    "reopen": "重新編輯",
}


def allowed_from(action: str) -> frozenset[Status]:
    return TRANSITIONS[action][0]


def target_of(action: str) -> Status | None:
    return TRANSITIONS[action][1]


def require(post: dict, action: str) -> None:
    """Raise 409 when `action` is not allowed from the post's current status."""
    allowed = allowed_from(action)
    if post["status"] not in allowed:
        raise Conflict(
            f"目前狀態「{post['status']}」不能{ACTION_LABELS[action]}",
            detail={"status": post["status"], "action": action, "allowed_from": sorted(allowed)},
        )
