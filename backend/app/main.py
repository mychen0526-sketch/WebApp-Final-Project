"""FastAPI entry point: `uvicorn app.main:app --reload` (run from backend/)."""
import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .container import Services, build_services
from .errors import NotFound, install_handlers
from .jobs import LAMBDA_EVENTS_PATH, Forbidden, on_lambda, run_event
from .routers import accounts, candidates, posts, research, settings, templates
from .services.scheduler import scheduler_loop
from .services.storage import MemoryStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class InsecureConfig(RuntimeError):
    pass


def create_app(services: Services | None = None, app_settings: Settings | None = None) -> FastAPI:
    cfg = services.settings if services else (app_settings or get_settings())
    problems = cfg.security_problems()
    if problems:
        # real publishing with a guessable APP_SECRET would let anyone forge the OAuth state and
        # bind their own Threads / IG / LinkedIn account to someone else's workspace
        raise InsecureConfig("拒絕啟動：" + "；".join(problems))
    services = services or build_services(cfg)
    if on_lambda():
        # every cold start would otherwise sweep tokens at once; the hourly `refresh_tokens` event does it
        services.last_token_refresh = time.monotonic()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(scheduler_loop(services)) if cfg.scheduler_enabled else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="跨平台 AI 社群圖文生成與發布平台 API",
        version="0.1.0",
        description="輸入目標 → AI 生成 → 編輯 → 本人審核 → 發布到 Threads / Instagram / LinkedIn",
        lifespan=lifespan,
    )
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_handlers(app)
    for module in (accounts, candidates, posts, research, settings, templates):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health():
        return {
            "ok": True,
            "database": "supabase" if cfg.use_supabase else "memory",
            "ai": "mock" if cfg.ai_is_mock else "rap",
            "image": cfg.image_backend,
            "publish": "mock" if cfg.mock_publish else "live",
            "search": services.research.name if services.research else "off",
        }

    @app.post(LAMBDA_EVENTS_PATH, include_in_schema=False)
    async def lambda_event(request: Request):
        """Non-HTTP Lambda events (async jobs, EventBridge schedules), forwarded by Lambda Web Adapter."""
        try:
            event = await request.json()
        except ValueError:
            return Response(status_code=400)
        if not isinstance(event, dict):
            return Response(status_code=400)
        try:
            job = await run_in_threadpool(run_event, services, event)
        except Forbidden:
            return Response(status_code=403)
        return {"ok": True, "job": job}

    if isinstance(services.storage, MemoryStorage):
        storage = services.storage

        @app.get("/dev-files/{path:path}", include_in_schema=False)
        def dev_file(path: str):
            item = storage.get(path)
            if not item:
                raise NotFound("檔案不存在")
            return Response(content=item[0], media_type=item[1])

    return app


app = create_app()
