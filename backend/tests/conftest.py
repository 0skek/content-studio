from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.channels import get_channel_specs
from app.clock import VirtualClock
from app.db import Base, get_session, make_engine
from app.generation_clients import GenerationClients
from app.main import app
from app.models import Brief, GenerationStatus, Language, Post, PostStatus
from app.post_status import transition
from app.dependencies import get_clock, get_generation_clients, get_media_dir, get_session_factory
from tests.fakes import FakeImageClient, FakeTextClient, make_jpeg

TEST_REJECTION_REASON = "Caption exceeds the channel limit (test)"
TEST_NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

# The transition() calls that lead from a fresh draft to each status.
TRANSITION_PATH_FROM_DRAFT: dict[PostStatus, list[PostStatus]] = {
    PostStatus.DRAFT: [],
    PostStatus.APPROVED: [PostStatus.APPROVED],
    PostStatus.DISCARDED: [PostStatus.DISCARDED],
    PostStatus.SCHEDULED: [PostStatus.APPROVED, PostStatus.SCHEDULED],
    PostStatus.PUBLISHED: [PostStatus.APPROVED, PostStatus.SCHEDULED, PostStatus.PUBLISHED],
    PostStatus.REJECTED: [PostStatus.APPROVED, PostStatus.SCHEDULED, PostStatus.REJECTED],
}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    # A real file, not :memory:, because generation jobs write from several threads at once.
    test_engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as test_session:
        yield test_session


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    path = tmp_path / "media"
    path.mkdir()
    return path


@pytest.fixture
def fake_text() -> FakeTextClient:
    return FakeTextClient(channels=list(get_channel_specs()))


@pytest.fixture
def fake_images() -> FakeImageClient:
    return FakeImageClient()


@pytest.fixture
def generation_clients(fake_text: FakeTextClient, fake_images: FakeImageClient) -> GenerationClients:
    return GenerationClients(text=fake_text, images=fake_images)


@pytest.fixture
def test_clock() -> VirtualClock:
    """A clock whose real time stands still at TEST_NOW; fast-forwarding still moves it."""
    return VirtualClock(real_now=lambda: TEST_NOW)


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    generation_clients: GenerationClients,
    media_dir: Path,
    test_clock: VirtualClock,
) -> Iterator[TestClient]:
    def get_test_session() -> Iterator[Session]:
        with session_factory() as request_session:
            yield request_session

    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_generation_clients] = lambda: generation_clients
    app.dependency_overrides[get_media_dir] = lambda: media_dir
    app.dependency_overrides[get_clock] = lambda: test_clock
    # Not used as a context manager, so the app lifespan (which touches the real database file) never runs.
    # Background tasks still run to completion before each request call returns.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def brief(session: Session) -> Brief:
    test_brief = Brief(
        title="Pohela Boishakh sale",
        goal="Drive visits to the new-year collection",
        audience="Young professionals in Dhaka",
        languages=[Language.BENGALI, Language.ENGLISH],
        tone="warm, festive",
    )
    session.add(test_brief)
    session.commit()
    return test_brief


@pytest.fixture
def make_post_in_status(session: Session, brief: Brief) -> Callable[..., Post]:
    """Create a committed post that reached `status` through real transition() calls."""

    def make(
        status: PostStatus,
        *,
        channel: str = "instagram",
        language: Language = Language.ENGLISH,
        generation: GenerationStatus = GenerationStatus.READY,
    ) -> Post:
        # Generation defaults to ready, because only ready drafts can be approved.
        post = Post(
            brief=brief,
            channel=channel,
            language=language,
            caption="Test caption",
            hashtags=["test"],
            generation_status=generation,
        )
        session.add(post)
        session.flush()
        for next_status in TRANSITION_PATH_FROM_DRAFT[status]:
            reason = TEST_REJECTION_REASON if next_status == PostStatus.REJECTED else None
            transition(post, next_status, rejection_reason=reason)
        session.commit()
        return post

    return make


@pytest.fixture
def make_publishable_post(session: Session, brief: Brief, media_dir: Path) -> Callable[..., Post]:
    """A generated post with a real final image on disk, approved and (by default) scheduled to be due now.

    Pass image_bytes, caption or hashtags that break a channel limit to see what the adapter does with them.
    """

    def make(
        *,
        channel: str = "x",
        caption: str = "Eid outfits for the whole family",
        hashtags: tuple[str, ...] = ("Eid",),
        image_bytes: bytes | None = None,
        scheduled_at: datetime | None = TEST_NOW - timedelta(minutes=1),
    ) -> Post:
        spec = get_channel_specs()[channel].image
        post = Post(
            brief=brief,
            channel=channel,
            language=Language.ENGLISH,
            headline="Eid together",
            caption=caption,
            hashtags=list(hashtags),
            generation_status=GenerationStatus.READY,
        )
        session.add(post)
        session.flush()
        post.image_path = f"briefs/{brief.id}/{channel}-en-post{post.id}.jpg"
        image_file = media_dir / post.image_path
        image_file.parent.mkdir(parents=True, exist_ok=True)
        image_file.write_bytes(image_bytes if image_bytes is not None else make_jpeg(spec.width, spec.height))
        transition(post, PostStatus.APPROVED)
        if scheduled_at is not None:
            transition(post, PostStatus.SCHEDULED)
            post.scheduled_at = scheduled_at
        session.commit()
        return post

    return make
