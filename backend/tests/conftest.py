from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session, make_engine
from app.main import app
from app.models import Brief, Language, Post, PostStatus
from app.post_status import transition

IN_MEMORY_DATABASE_URL = "sqlite://"
TEST_REJECTION_REASON = "Caption exceeds the channel limit (test)"

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
def engine() -> Iterator[Engine]:
    # StaticPool keeps one connection, so every session sees the same in-memory database.
    test_engine = make_engine(IN_MEMORY_DATABASE_URL, poolclass=StaticPool)
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
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def get_test_session() -> Iterator[Session]:
        with session_factory() as request_session:
            yield request_session

    app.dependency_overrides[get_session] = get_test_session
    # Not used as a context manager, so the app lifespan (which touches the real database file) never runs.
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

    def make(status: PostStatus, *, channel: str = "instagram", language: Language = Language.ENGLISH) -> Post:
        post = Post(brief=brief, channel=channel, language=language, caption="Test caption", hashtags=["test"])
        session.add(post)
        session.flush()
        for next_status in TRANSITION_PATH_FROM_DRAFT[status]:
            reason = TEST_REJECTION_REASON if next_status == PostStatus.REJECTED else None
            transition(post, next_status, rejection_reason=reason)
        session.commit()
        return post

    return make
