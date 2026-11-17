"""FastAPI entry point: `uvicorn app.main:app --reload` (run from backend/)."""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .container import Services, build_services
from .errors import NotFound, install_handlers
from .routers import accounts, candidates, posts, settings, templates
from .services.scheduler import scheduler_loop
from .services.storage import MemoryStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(services: Services | None = None, app_settings: Settings | None = None) -> FastAPI:
    services = services or build_services(app_settings or get_settings())
    cfg = services.settings

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
        description="輸入目標 → AI 生成 → 編輯 → 本人審核 → 發布到 Threads / Instagram",
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
    for module in (accounts, candidates, posts, settings, templates):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health():
        return {
            "ok": True,
            "database": "supabase" if cfg.use_supabase else "memory",
            "ai": "mock" if cfg.ai_is_mock else "rap",
            "image": cfg.image_backend,
            "publish": "mock" if cfg.mock_publish else "live",
        }

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
