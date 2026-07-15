import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app
from app.models.location import Location
from app.routers.locations import get_db as get_db_loc
from app.routers.matches import get_db as get_db_mat
from app.services.match_service import compute_available_rounds

from sqlalchemy.pool import StaticPool

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

    app.dependency_overrides[get_db_loc] = override_get_db
    app.dependency_overrides[get_db_mat] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def seed_test_locations(db):
    # Seeding locations across at least 3 distinct l_dong_signgu_cd values and 3 distinct category values
    locations = [
        # District "110" (종로구)
        Location(content_id="loc1", content_type_id="12", category="tourist_spot", title="종로 관광지", l_dong_signgu_cd="110", sigungu_name="종로구"),
        Location(content_id="loc2", content_type_id="14", category="culture_facility", title="종로 문화시설", l_dong_signgu_cd="110", sigungu_name="종로구"),
        # District "140" (중구)
        Location(content_id="loc3", content_type_id="15", category="festival", title="중구 축제", l_dong_signgu_cd="140", sigungu_name="중구"),
        Location(content_id="loc4", content_type_id="12", category="tourist_spot", title="중구 관광지", l_dong_signgu_cd="140", sigungu_name="중구"),
        # District "680" (강남구)
        Location(content_id="loc5", content_type_id="38", category="shopping", title="강남 쇼핑", l_dong_signgu_cd="680", sigungu_name="강남구"),
        Location(content_id="loc6", content_type_id="12", category="tourist_spot", title="강남 관광지", l_dong_signgu_cd="680", sigungu_name="강남구"),
        Location(content_id="loc7", content_type_id="28", category="leports", title="강남 레포츠", l_dong_signgu_cd="680", sigungu_name="강남구"),
        Location(content_id="loc8", content_type_id="32", category="accommodation", title="강남 숙박", l_dong_signgu_cd="680", sigungu_name="강남구"),
    ]
    for loc in locations:
        db.add(loc)
    db.commit()


# 6.1 Unit tests — pure logic
def test_compute_available_rounds():
    assert compute_available_rounds(3) == []
    assert compute_available_rounds(4) == [4]
    assert compute_available_rounds(50) == [4, 8, 16, 32]
    assert compute_available_rounds(100) == [4, 8, 16, 32, 64]


# 6.2 Integration tests — candidate filtering
def test_candidate_filtering(db, client):
    seed_test_locations(db)

    # regions=["ALL"], categories=["ALL"]
    response = client.get("/api/locations/candidates?regions=ALL&categories=ALL")
    assert response.status_code == 200
    assert response.json()["candidate_count"] == 8
    assert response.json()["available_rounds"] == [4, 8]

    # regions=[<one code>], categories=["ALL"]
    response = client.get("/api/locations/candidates?regions=110&categories=ALL")
    assert response.status_code == 200
    assert response.json()["candidate_count"] == 2

    # regions=["ALL"], categories=[<one category>]
    response = client.get("/api/locations/candidates?regions=ALL&categories=tourist_spot")
    assert response.status_code == 200
    assert response.json()["candidate_count"] == 3

    # regions=[<code A>, <code B>], categories=[<cat X>] (AND intersection)
    response = client.get("/api/locations/candidates?regions=110&regions=140&categories=tourist_spot")
    assert response.status_code == 200
    assert response.json()["candidate_count"] == 2


# 6.3 Integration tests — match creation
def test_match_creation(db, client):
    seed_test_locations(db)

    # Exceeds candidate count -> 400
    response = client.post("/api/matches", json={
        "regions": ["ALL"],
        "categories": ["ALL"],
        "total_rounds": 16
    })
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "ROUND_EXCEEDS_CANDIDATES"

    # Verify no partial writes
    from app.models.match import Match, MatchFilter, MatchGame
    assert db.query(Match).count() == 0
    assert db.query(MatchFilter).count() == 0
    assert db.query(MatchGame).count() == 0

    # Valid match creation with total_rounds=4
    response = client.post("/api/matches", json={
        "regions": ["110", "680"],
        "categories": ["ALL"],
        "total_rounds": 4
    })
    assert response.status_code == 201
    data = response.json()
    assert data["total_rounds"] == 4
    assert data["status"] == "in_progress"
    assert data["current_round_no"] == 1
    assert data["total_round_count"] == 2
    assert "first_game" in data

    # Verify rows
    match = db.query(Match).first()
    assert match is not None
    assert match.total_rounds == 4
    assert match.status == "in_progress"

    filters = db.query(MatchFilter).all()
    assert len(filters) == 3  # Two regions (110, 680), One category (ALL)
    
    games = db.query(MatchGame).all()
    assert len(games) == 2
    for g in games:
        assert g.round_no == 1
        assert g.winner_id is None
        assert g.is_final is False

    first_game_resp = data["first_game"]
    assert first_game_resp["order_in_round"] == 0
    assert first_game_resp["round_no"] == 1


# 6.4 Integration tests — full match playthrough
def test_full_match_playthrough(db, client):
    seed_test_locations(db)

    # Create match
    response = client.post("/api/matches", json={
        "regions": ["ALL"],
        "categories": ["ALL"],
        "total_rounds": 4
    })
    assert response.status_code == 201
    match_data = response.json()
    match_id = match_data["match_id"]
    
    from app.models.match import MatchGame, Match
    games = db.query(MatchGame).filter(MatchGame.match_id == match_id).all()
    assert len(games) == 2

    game0 = next(g for g in games if g.order_in_round == 0)
    game1 = next(g for g in games if g.order_in_round == 1)

    # Call result endpoint before finish -> 409
    response = client.get(f"/api/matches/{match_id}/result")
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "MATCH_NOT_FINISHED"

    # Play round 1, game 0
    response = client.post(
        f"/api/matches/{match_id}/games/{game0.id}/result",
        json={"winner_id": game0.location_a_id}
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["is_final_result"] is False
    assert res_data["status"] == "in_progress"
    assert res_data["next_game"]["id"] == game1.id
    assert res_data["winner_location_id"] is None

    # Play round 1, game 1
    response = client.post(
        f"/api/matches/{match_id}/games/{game1.id}/result",
        json={"winner_id": game1.location_b_id}
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["is_final_result"] is False
    assert res_data["status"] == "in_progress"

    # Round 2 game is generated
    round2_game_id = res_data["next_game"]["id"]
    db_round2_game = db.query(MatchGame).filter(MatchGame.id == round2_game_id).first()
    assert db_round2_game is not None
    assert db_round2_game.round_no == 2
    assert db_round2_game.is_final is True
    assert db_round2_game.location_a_id == game0.location_a_id
    assert db_round2_game.location_b_id == game1.location_b_id

    # Play final game
    response = client.post(
        f"/api/matches/{match_id}/games/{round2_game_id}/result",
        json={"winner_id": game0.location_a_id}
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["is_final_result"] is True
    assert res_data["status"] == "finished"
    assert res_data["next_game"] is None
    assert res_data["winner_location_id"] == game0.location_a_id

    # Match state finished in DB
    db_match = db.query(Match).filter(Match.id == match_id).first()
    assert db_match.status == "finished"
    assert db_match.finished_at is not None

    # GET /api/matches/{match_id}/result works now
    response = client.get(f"/api/matches/{match_id}/result")
    assert response.status_code == 200
    result_data = response.json()
    assert result_data["match_id"] == match_id
    assert result_data["winner_location"]["id"] == game0.location_a_id


def test_full_match_playthrough_8_rounds(db, client):
    seed_test_locations(db)

    # Create 8 rounds match
    response = client.post("/api/matches", json={
        "regions": ["ALL"],
        "categories": ["ALL"],
        "total_rounds": 8
    })
    assert response.status_code == 201
    match_id = response.json()["match_id"]

    from app.models.match import MatchGame
    r1_games = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.round_no == 1
    ).order_by(MatchGame.order_in_round.asc()).all()
    assert len(r1_games) == 4

    r1_winners = []
    for g in r1_games:
        client.post(
            f"/api/matches/{match_id}/games/{g.id}/result",
            json={"winner_id": g.location_a_id}
        )
        r1_winners.append(g.location_a_id)

    # Verify round 2 generated
    r2_games = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.round_no == 2
    ).order_by(MatchGame.order_in_round.asc()).all()
    assert len(r2_games) == 2
    assert r2_games[0].location_a_id == r1_winners[0]
    assert r2_games[0].location_b_id == r1_winners[1]
    assert r2_games[1].location_a_id == r1_winners[2]
    assert r2_games[1].location_b_id == r1_winners[3]

    r2_winners = []
    for g in r2_games:
        client.post(
            f"/api/matches/{match_id}/games/{g.id}/result",
            json={"winner_id": g.location_a_id}
        )
        r2_winners.append(g.location_a_id)

    # Verify round 3 (final) generated
    r3_games = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.round_no == 3
    ).all()
    assert len(r3_games) == 1
    assert r3_games[0].is_final is True
    assert r3_games[0].location_a_id == r2_winners[0]
    assert r3_games[0].location_b_id == r2_winners[1]


# 6.5 Integration tests — error cases
def test_error_cases(db, client):
    seed_test_locations(db)

    # 1. GET candidates 422 (validation error due to empty params)
    response = client.get("/api/locations/candidates")
    assert response.status_code == 422

    # 2. GET locations/{id} 404
    response = client.get("/api/locations/9999")
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "LOCATION_NOT_FOUND"

    # Create match
    response = client.post("/api/matches", json={
        "regions": ["ALL"],
        "categories": ["ALL"],
        "total_rounds": 4
    })
    match_id = response.json()["match_id"]
    from app.models.match import MatchGame
    game = db.query(MatchGame).filter(MatchGame.match_id == match_id).first()

    # 3. GET matches/{id} 404
    response = client.get("/api/matches/9999")
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "MATCH_NOT_FOUND"

    # 4. POST games/{id}/result 404
    response = client.post(
        f"/api/matches/{match_id}/games/9999/result",
        json={"winner_id": game.location_a_id}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "GAME_NOT_FOUND"

    # 5. POST games/{id}/result 400 (invalid winner)
    response = client.post(
        f"/api/matches/{match_id}/games/{game.id}/result",
        json={"winner_id": 9999}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "INVALID_WINNER"

    # Complete game
    client.post(
        f"/api/matches/{match_id}/games/{game.id}/result",
        json={"winner_id": game.location_a_id}
    )

    # 6. POST games/{id}/result 409 (already completed)
    response = client.post(
        f"/api/matches/{match_id}/games/{game.id}/result",
        json={"winner_id": game.location_a_id}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error_code"] == "GAME_ALREADY_COMPLETED"


def test_match_finished_errors(db, client):
    seed_test_locations(db)

    # Create and play complete match
    response = client.post("/api/matches", json={
        "regions": ["ALL"],
        "categories": ["ALL"],
        "total_rounds": 4
    })
    match_id = response.json()["match_id"]
    from app.models.match import MatchGame
    games = db.query(MatchGame).filter(MatchGame.match_id == match_id).all()
    game0 = next(g for g in games if g.order_in_round == 0)
    game1 = next(g for g in games if g.order_in_round == 1)

    client.post(f"/api/matches/{match_id}/games/{game0.id}/result", json={"winner_id": game0.location_a_id})
    client.post(f"/api/matches/{match_id}/games/{game1.id}/result", json={"winner_id": game1.location_a_id})

    # Round 2
    r2_game = db.query(MatchGame).filter(MatchGame.match_id == match_id, MatchGame.round_no == 2).first()
    client.post(f"/api/matches/{match_id}/games/{r2_game.id}/result", json={"winner_id": game0.location_a_id})

    # 7. GET matches/{id} 409 on finished match
    response = client.get(f"/api/matches/{match_id}")
    assert response.status_code == 409
    data = response.json()["detail"]
    assert data["error_code"] == "MATCH_ALREADY_FINISHED"
    assert data["redirect_to"] == f"/worldcup/{match_id}/result"


# 6.6 Resume/recovery test
def test_resume_and_recovery(db, client):
    seed_test_locations(db)

    response = client.post("/api/matches", json={
        "regions": ["ALL"],
        "categories": ["ALL"],
        "total_rounds": 4
    })
    match_id = response.json()["match_id"]
    from app.models.match import MatchGame
    games = db.query(MatchGame).filter(MatchGame.match_id == match_id).all()
    game0 = next(g for g in games if g.order_in_round == 0)
    game1 = next(g for g in games if g.order_in_round == 1)

    # Play game 0
    client.post(f"/api/matches/{match_id}/games/{game0.id}/result", json={"winner_id": game0.location_a_id})

    # Call GET /api/matches/{match_id} (resume)
    response = client.get(f"/api/matches/{match_id}")
    assert response.status_code == 200
    state = response.json()
    assert state["current_round_no"] == 1
    assert state["round_display"] == "4강 2번째 경기"
    assert state["current_game"]["id"] == game1.id
