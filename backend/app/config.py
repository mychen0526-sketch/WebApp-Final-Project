"""Settings loaded from environment variables or backend/.env."""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


WEAK_SECRETS = {"", "change-me-in-env", "change-me-to-a-long-random-string"}


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

    # Signs the OAuth `state` parameter. With real publishing (MOCK_PUBLISH=false) the server
    # refuses to start while this is still a template value or shorter than 32 characters.
    app_secret: str = "change-me-in-env"
    # Fernet key (base64, 32 bytes) for social access tokens at rest. Empty: derived from APP_SECRET.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""
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
    # A post still `publishing` after this long (worker crashed / restarted mid-publish) is moved
    # to publish_failed; platforms whose result is unknown are flagged "uncertain" (check first).
    publish_stale_minutes: int = 15
    # Temporary platform errors (5xx, 429, network) are retried this many times before giving up
    publish_transient_retries: int = 2
    publish_retry_backoff_seconds: float = 2.0
    # Threads / Instagram long-lived tokens are refreshed when they expire within this many days
    token_refresh_days: int = 7

    def security_problems(self) -> list[str]:
        """Settings that must not reach a deployment that publishes for real."""
        problems = []
        if self.mock_publish:
            return problems
        if self.app_secret in WEAK_SECRETS or len(self.app_secret) < 32:
            problems.append("APP_SECRET 仍是範本值或少於 32 字元，請換成隨機長字串")
        if self.token_encryption_key:
            try:
                from cryptography.fernet import Fernet

                Fernet(self.token_encryption_key.encode())
            except ValueError:
                problems.append("TOKEN_ENCRYPTION_KEY 不是有效的 Fernet 金鑰")
        return problems

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


def load_env_parameter() -> None:
    """On AWS Lambda the whole .env lives in one SSM SecureString parameter (ENV_PARAMETER) rather
    than in plain function environment variables. Its keys fill os.environ unless already set."""
    name = os.environ.get("ENV_PARAMETER")
    if not name:
        return
    import io

    import boto3  # bundled with the Lambda Python runtime
    from dotenv import dotenv_values

    text = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    for key, value in dotenv_values(stream=io.StringIO(text)).items():
        if value is not None:
            os.environ.setdefault(key, value)


@lru_cache
def get_settings() -> Settings:
    load_env_parameter()
    return Settings()
