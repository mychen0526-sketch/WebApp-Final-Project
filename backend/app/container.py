"""Wires settings to concrete implementations (Supabase vs memory, RAP/fal vs mock, real vs mock publish)."""
from dataclasses import dataclass, field

from .config import Settings
from .repo.base import Repo
from .repo.memory_repo import MemoryRepo
from .services.ai import AIService, MockAI, RapAI
from .services.images import FalFlux, FluxImageAI
from .services.platforms.base import Publisher
from .services.platforms.instagram import InstagramPublisher
from .services.platforms.linkedin import LinkedInPublisher
from .services.platforms.mock import MockPublisher
from .services.platforms.threads import ThreadsPublisher
from .services.progress import ProgressHub
from .services.research import Research, build_research
from .services.webfetch import Fetcher, SafeFetcher
from .services.storage import MemoryStorage, Storage, SupabaseStorage
from .services.tokens import TokenCipher


@dataclass
class Services:
    settings: Settings
    repo: Repo
    storage: Storage
    ai: AIService
    publishers: dict[str, Publisher] = field(default_factory=dict)
    progress: ProgressHub = field(default_factory=ProgressHub)
    # News search (趨勢情報) and the downloader for the pictures it finds. Tests swap both.
    research: Research | None = None
    fetcher: Fetcher = field(default_factory=SafeFetcher)
    # Encrypts social access tokens at rest (built from settings when not given)
    tokens: TokenCipher | None = None
    last_token_refresh: float = 0.0  # monotonic time of the scheduler's last token-refresh sweep

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = TokenCipher(self.settings.token_encryption_key, self.settings.app_secret)


def build_ai(settings: Settings) -> AIService:
    """Text from TAIWAN AI RAP (or mock); card background from fal (or a gradient)."""
    text = (
        MockAI(stream_delay=0.04)  # slow enough to see the caption stream in local dev
        if settings.ai_is_mock
        else RapAI(settings.rap_api_key, settings.rap_base_url, settings.rap_text_model, settings.ai_timeout_seconds)
    )
    if settings.image_backend == "fal":
        backend = FalFlux(
            settings.fal_api_key,
            settings.fal_image_model,
            settings.ai_timeout_seconds,
            blend_model=settings.fal_blend_model,
            blend_strength=settings.fal_blend_strength,
        )
        return FluxImageAI(text, backend)
    return text if isinstance(text, MockAI) else FluxImageAI(text, None)


def build_services(settings: Settings) -> Services:
    if settings.use_supabase:
        from supabase import create_client

        from .repo.supabase_repo import SupabaseRepo

        client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        repo: Repo = SupabaseRepo(client)
        storage: Storage = SupabaseStorage(client, settings.storage_bucket)
    else:
        repo = MemoryRepo()
        storage = MemoryStorage(settings.public_base_url)

    ai: AIService = build_ai(settings)

    if settings.mock_publish:
        publishers: dict[str, Publisher] = {p: MockPublisher(p) for p in ("threads", "instagram", "linkedin")}
    else:
        poll = dict(poll_attempts=settings.publish_poll_attempts, poll_interval=settings.publish_poll_interval_seconds)
        publishers = {
            "threads": ThreadsPublisher(
                settings.threads_app_id, settings.threads_app_secret, settings.threads_redirect_uri, **poll
            ),
            "instagram": InstagramPublisher(
                settings.instagram_app_id,
                settings.instagram_app_secret,
                settings.instagram_redirect_uri,
                settings.instagram_api_version,
                **poll,
            ),
            "linkedin": LinkedInPublisher(
                settings.linkedin_client_id,
                settings.linkedin_client_secret,
                settings.linkedin_redirect_uri,
                settings.linkedin_api_version,
                fetcher=SafeFetcher(timeout=30),
            ),
        }
    return Services(
        settings=settings,
        repo=repo,
        storage=storage,
        ai=ai,
        publishers=publishers,
        research=build_research(settings),
    )
