"""Background work (generation, publishing, scheduled sweeps) that survives AWS Lambda.

Locally (uvicorn) jobs run as FastAPI background tasks in the same process, as before.

On Lambda the execution environment is frozen as soon as the response is sent, so a background
task would stall half-way. There, `dispatch` asynchronously invokes this same function with a
signed job event instead. Lambda Web Adapter forwards non-HTTP events as a POST to
AWS_LWA_PASS_THROUGH_PATH (= LAMBDA_EVENTS_PATH below), where `run_event` runs the job to the end.

That path is also reachable through the public Function URL, so jobs that act on a user's data
are HMAC-signed with a key derived from APP_SECRET. The EventBridge `tick` / `refresh_tokens`
events carry no user data and only do work that is already due, so they need no signature.
"""
import hashlib
import hmac
import json
import logging
import os

from fastapi import BackgroundTasks

from .services.generation import run_generation
from .services.publishing import publish_post
from .services.scheduler import refresh_expiring_tokens, run_due_once

log = logging.getLogger(__name__)

LAMBDA_EVENTS_PATH = "/internal/lambda-events"
SIGNED_JOBS = {"generate", "publish"}


def on_lambda() -> bool:
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _key(services) -> bytes:
    return hmac.new(services.settings.app_secret.encode(), b"lambda-job-v1", hashlib.sha256).digest()


def _body(job: str, args: dict) -> bytes:
    return json.dumps({"job": job, "args": args}, sort_keys=True, ensure_ascii=False, default=str).encode()


def sign(services, job: str, args: dict) -> str:
    return hmac.new(_key(services), _body(job, args), hashlib.sha256).hexdigest()


def _run(services, job: str, args: dict) -> None:
    if job == "generate":
        # no progress token: the run starts its own entry in this process's ProgressHub
        run_generation(services, args["user_id"], args["post_id"], args["choice"], args.get("mode"))
    elif job == "publish":
        post = services.repo.get_post(args["user_id"], args["post_id"])
        if post:
            publish_post(services, post, args.get("targets"), args.get("confirmed"))
    elif job == "tick":
        run_due_once(services)
    elif job == "refresh_tokens":
        refresh_expiring_tokens(services)
    else:
        raise ValueError(f"unknown job {job!r}")


def dispatch(services, background: BackgroundTasks, job: str, **args) -> None:
    """Run `job` after the response: in-process locally, as an async Lambda invocation on AWS."""
    if not on_lambda():
        background.add_task(_run, services, job, args)
        return
    import boto3  # bundled with the Lambda Python runtime

    payload = {"job": job, "args": args, "sig": sign(services, job, args)}
    boto3.client("lambda").invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps(payload, ensure_ascii=False, default=str).encode(),
    )


class Forbidden(Exception):
    pass


def run_event(services, event: dict) -> str:
    """Handle one event forwarded by Lambda Web Adapter. Returns the job name."""
    job = event.get("job")
    args = event.get("args") or {}
    if job in SIGNED_JOBS:
        if not hmac.compare_digest(str(event.get("sig", "")), sign(services, job, args)):
            raise Forbidden(job)
    elif job not in {"tick", "refresh_tokens"}:
        raise Forbidden(str(job))
    _run(services, job, args)
    return job
