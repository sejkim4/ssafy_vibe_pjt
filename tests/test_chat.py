from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app
from app.models.location import Location
from app.models.match import Match, MatchGame
from app.models.review import Review
from app.routers.chat import get_db as get_db_chat


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)


@pytest.fixture(name="db")
def session_fixture():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def client_fixture(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db_chat] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(name="openai_mock")
def openai_mock_fixture(monkeypatch):
    import openai

    calls = []

    class FakeMessage:
        content = "mocked reply"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs["messages"])
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    return calls


def seed_chat_game(db, *, match_status="in_progress", winner_id=None):
    loc_a = Location(
        id=101,
        content_id="chat-a",
        content_type_id="12",
        category="tourist_spot",
        title="A Spot",
        addr1="Seoul A-ro 1",
        l_dong_signgu_cd="110",
        sigungu_name="Jongno-gu",
        lcls_systm_1="LS1",
    )
    loc_b = Location(
        id=102,
        content_id="chat-b",
        content_type_id="14",
        category="culture_facility",
        title="B Museum",
        addr1="Seoul B-ro 2",
        l_dong_signgu_cd="140",
        sigungu_name="Jung-gu",
    )
    match = Match(
        id=201,
        total_rounds=4,
        status=match_status,
        created_at=datetime.utcnow(),
        finished_at=datetime.utcnow() if match_status == "finished" else None,
    )
    game = MatchGame(
        id=301,
        match_id=match.id,
        round_no=1,
        order_in_round=0,
        location_a_id=loc_a.id,
        location_b_id=loc_b.id,
        winner_id=winner_id,
        is_final=False,
        completed_at=datetime.utcnow() if winner_id else None,
    )
    db.add_all([loc_a, loc_b, match, game])
    db.commit()
    return match, game, loc_a, loc_b


def post_chat(client, match_id=201, game_id=301, **overrides):
    payload = {
        "match_id": match_id,
        "game_id": game_id,
        "message": "Which one is better for a quiet visit?",
        "history": [],
    }
    payload.update(overrides)
    return client.post("/api/chat", json=payload)


def system_prompt_from(openai_calls):
    return openai_calls[0][0]["content"]


def test_chat_happy_path_includes_both_location_names(db, client, openai_mock):
    seed_chat_game(db)

    response = post_chat(client)

    assert response.status_code == 200
    assert response.json() == {"reply": "mocked reply"}
    assert len(openai_mock) == 1
    prompt = system_prompt_from(openai_mock)
    assert "A Spot" in prompt
    assert "B Museum" in prompt


def test_chat_prompt_contains_anti_hallucination_instruction(db, client, openai_mock):
    seed_chat_game(db)

    response = post_chat(client)

    assert response.status_code == 200
    prompt = system_prompt_from(openai_mock)
    assert "추측하거나 지어내지 말고" in prompt
    assert "제공된 정보만으로는 알 수 없습니다" in prompt


def test_chat_includes_reviews_under_correct_location_section(db, client, openai_mock):
    _, _, loc_a, loc_b = seed_chat_game(db)
    db.add_all(
        [
            Review(
                location_id=loc_a.id,
                nickname="one",
                content="A review says the garden is calm.",
                password="pw",
                created_at=datetime.utcnow(),
            ),
            Review(
                location_id=loc_b.id,
                nickname="two",
                content="B review says the exhibition is bright.",
                password="pw",
                created_at=datetime.utcnow() - timedelta(days=1),
            ),
        ]
    )
    db.commit()

    response = post_chat(client)

    assert response.status_code == 200
    prompt = system_prompt_from(openai_mock)
    a_review_index = prompt.index("\nA 사용자 리뷰")
    b_location_index = prompt.index("\nB 장소 정보")
    b_review_index = prompt.index("\nB 사용자 리뷰")
    assert a_review_index < b_location_index
    assert b_review_index > b_location_index
    assert "A review says the garden is calm." in prompt[a_review_index:b_location_index]
    assert "B review says the exhibition is bright." in prompt[b_review_index:]


def test_chat_prompt_frames_reviews_as_opinion(db, client, openai_mock):
    seed_chat_game(db)

    response = post_chat(client)

    assert response.status_code == 200
    prompt = system_prompt_from(openai_mock)
    assert "주관적 의견" in prompt
    assert "검증된 사실이 아닙니다" in prompt


def test_chat_omits_empty_review_section(db, client, openai_mock):
    _, _, loc_a, _ = seed_chat_game(db)
    db.add(
        Review(
            location_id=loc_a.id,
            nickname="one",
            content="Only A has a review.",
            password="pw",
            created_at=datetime.utcnow(),
        )
    )
    db.commit()

    response = post_chat(client)

    assert response.status_code == 200
    prompt = system_prompt_from(openai_mock)
    assert "A 사용자 리뷰" in prompt
    assert "B 사용자 리뷰" not in prompt


def test_chat_unknown_game_returns_404_without_openai_call(db, client, openai_mock):
    seed_chat_game(db)

    response = post_chat(client, game_id=999)

    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "GAME_NOT_FOUND"
    assert openai_mock == []


def test_chat_finished_match_returns_409_without_openai_call(db, client, openai_mock):
    seed_chat_game(db, match_status="finished")

    response = post_chat(client)

    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "MATCH_ALREADY_FINISHED"
    assert openai_mock == []


def test_chat_completed_game_allowed_when_match_in_progress(db, client, openai_mock):
    seed_chat_game(db, winner_id=101)

    response = post_chat(client)

    assert response.status_code == 200
    assert response.json()["reply"] == "mocked reply"
    assert len(openai_mock) == 1


def test_chat_empty_message_returns_422(db, client, openai_mock):
    seed_chat_game(db)

    response = post_chat(client, message="")

    assert response.status_code == 422
    assert openai_mock == []


def test_chat_upstream_failure_returns_502(db, client, monkeypatch):
    import openai

    seed_chat_game(db)

    class FailingCompletions:
        def create(self, **kwargs):
            raise openai.OpenAIError("boom")

    class FailingChat:
        completions = FailingCompletions()

    class FailingOpenAI:
        def __init__(self, **kwargs):
            self.chat = FailingChat()

    monkeypatch.setattr(openai, "OpenAI", FailingOpenAI)
    response = post_chat(client)

    assert response.status_code == 502
    assert response.json()["detail"]["error_code"] == "CHAT_UPSTREAM_ERROR"


def test_chat_history_passthrough_order(db, client, openai_mock):
    seed_chat_game(db)
    history = [
        {"role": "user", "content": "Tell me about A."},
        {"role": "assistant", "content": "A has location metadata only."},
    ]

    response = post_chat(client, message="Now compare B.", history=history)

    assert response.status_code == 200
    sent_messages = openai_mock[0]
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[1:3] == history
    assert sent_messages[3] == {"role": "user", "content": "Now compare B."}
