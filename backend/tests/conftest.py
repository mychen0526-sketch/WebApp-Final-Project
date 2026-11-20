import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Services
from app.main import create_app
from app.repo.memory_repo import MemoryRepo
from app.services.ai import MockAI
from app.services.platforms.mock import MockPublisher
from app.services.research import MockResearch
from app.services.webfetch import FetchError, Fetched
from app.services.storage import MemoryStorage

USER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
JWT_SECRET = "test-jwt-secret-at-least-32-bytes-long!!"

CANDIDATE = {"title": "新創的影響", "angle": "分析這次公告對 AI 新創商業化的影響", "hook": "如果你是新創，先想這三件事"}


def jpeg_bytes(width: int = 1200, height: int = 800) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(out, "JPEG")
    return out.getvalue()


class FakeFetcher:
    """No network in tests: URLs map to canned responses; anything else fails like a dead link."""

    def __init__(self) -> None:
        self.pages: dict[str, Fetched] = {}
        self.calls: list[str] = []

    def add(self, url: str, data: bytes, content_type: str = "image/jpeg") -> None:
        self.pages[url] = Fetched(url=url, content_type=content_type, data=data)

    def get(self, url, max_bytes, accept=()):
        self.calls.append(url)
        if url not in self.pages:
            raise FetchError("HTTP 404")
        return self.pages[url]


@pytest.fixture
def services() -> Services:
    settings = Settings(
        _env_file=None,
        supabase_url="",
        supabase_service_role_key="",
        supabase_jwt_secret=JWT_SECRET,
        mock_ai=True,
        mock_publish=True,
        dev_auth=True,
        scheduler_enabled=False,
        app_secret="test-app-secret-at-least-32-bytes-long!",
    )
    return Services(
        settings=settings,
        repo=MemoryRepo(),
        storage=MemoryStorage("http://testserver"),
        ai=MockAI(),
        publishers={p: MockPublisher(p) for p in ("threads", "instagram", "linkedin")},
        research=MockResearch(),
        fetcher=FakeFetcher(),
    )


@pytest.fixture
def client(services) -> TestClient:
    with TestClient(create_app(services)) as c:
        c.headers.update({"X-Dev-User": USER})
        yield c


@pytest.fixture
def other(services) -> TestClient:
    with TestClient(create_app(services)) as c:
        c.headers.update({"X-Dev-User": OTHER})
        yield c


# ---------------------------------------------------------------- flow helpers
def create_post(client, **extra) -> dict:
    body = {"goal": "分析 OpenAI 這次公告對 AI 新創商業化的影響", "tone": "專業分析", "selected": CANDIDATE, **extra}
    resp = client.post("/api/posts", json=body)
    assert resp.status_code == 202, resp.text
    # BackgroundTasks run before TestClient returns, so generation is already done
    return client.get(f"/api/posts/{resp.json()['id']}").json()


def connect(client, *platforms):
    for platform in platforms:
        assert client.get(f"/api/accounts/{platform}/connect").status_code == 200


def to_pending(client, platforms=("threads", "instagram")) -> dict:
    connect(client, *platforms)
    post = create_post(client)
    resp = client.post(f"/api/posts/{post['id']}/submit", json={"platforms": list(platforms)})
    assert resp.status_code == 200, resp.text
    return resp.json()


def to_approved(client, platforms=("threads", "instagram")) -> dict:
    post = to_pending(client, platforms)
    resp = client.post(f"/api/posts/{post['id']}/approve", json={"readConfirmed": True, "rightsConfirmed": True})
    assert resp.status_code == 200, resp.text
    return resp.json()
