"""Settings loaded from environment variables or backend/.env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase (PostgreSQL + Auth + Storage). Leave empty to use the in-memory repo for local dev.
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""  # only needed for projects that still sign JWTs with HS256
    storage_bucket: str = "post-images"

    # Text: TAIWAN AI RAP (NCHC), OpenAI-compatible chat completions
    rap_api_key: str = ""
    rap_base_url: str = "https://portal.genai.nchc.org.tw/api/v1"
    rap_text_model: str = "gemma-4-31B-it"
    ai_timeout_seconds: int = 90

    # Card background: FLUX.1 [schnell] on fal.ai (~US$0.003/image). No key → plain gradient.
    fal_api_key: str = ""
    fal_image_model: str = "fal-ai/flux/schnell"
    # 「AI 融合」: image-to-image on a real news photo (~US$0.025/MP). Same fal key.
    fal_blend_model: str = "fal-ai/flux/dev/image-to-image"
    fal_blend_strength: float = 0.82  # 0 = keep the photo, 1 = ignore it

    # News / trend search with lead pictures. "auto": Tavily when TAVILY_API_KEY is set, else the
    # free Bing News RSS feed; "mock": demo results (no network); "off": search disabled.
    search_backend: str = "auto"
    tavily_api_key: str = ""
    # Bing News markets, comma separated; all are searched and the results interleaved
    search_market: str = "zh-TW,en-US"

    # Mock switches: run the whole flow without external services
    mock_ai: bool = False
    mock_publish: bool = False
    # Accept an `X-Dev-User: <id>` header instead of a JWT. Ignored when Supabase is configured.
    dev_auth: bool = False

    # Signs the OAuth `state` parameter
    app_secret: str = "change-me-in-env"
    frontend_url: str = "http://127.0.0.1:5173"
    public_base_url: str = "http://127.0.0.1:8000"  # used for dev file URLs in memory mode
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    # Threads API
    threads_app_id: str = ""
    threads_app_secret: str = ""
    threads_redirect_uri: str = "http://127.0.0.1:8000/api/accounts/threads/callback"

    # Instagram API with Instagram Login
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_redirect_uri: str = "http://127.0.0.1:8000/api/accounts/instagram/callback"
    instagram_api_version: str = "v23.0"

    # LinkedIn: "Sign In with LinkedIn using OpenID Connect" + "Share on LinkedIn" products
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://127.0.0.1:8000/api/accounts/linkedin/callback"
    linkedin_api_version: str = "202605"  # YYYYMM sent as the LinkedIn-Version header

    # Background work
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 30
    publish_poll_interval_seconds: float = 3.0
    publish_poll_attempts: int = 10
    generation_stale_minutes: int = 10

    @property
    def use_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def ai_is_mock(self) -> bool:
        return self.mock_ai or not self.rap_api_key

    @property
    def search_mode(self) -> str:
        if self.search_backend != "auto":
            return self.search_backend
        if self.mock_ai:
            return "mock"
        return "tavily" if self.tavily_api_key else "rss"

    @property
    def image_backend(self) -> str:
        return "fal" if self.fal_api_key and not self.mock_ai else "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
