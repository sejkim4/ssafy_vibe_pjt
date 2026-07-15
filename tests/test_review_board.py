import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app
from app.models.location import Location
from app.models.match import Match, MatchGame
from app.models.review import Review
from app.routers.locations import get_db as get_db_loc
from app.routers.matches import get_db as get_db_mat
from app.routers.reviews import get_db as get_db_rev
from app.routers.board import get_db as get_db_brd

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
    app.dependency_overrides[get_db_rev] = override_get_db
    app.dependency_overrides[get_db_brd] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def assert_no_password_key(data):
    """Helper assertion to recursively verify no 'password' key exists in JSON data."""
    if isinstance(data, dict):
        assert "password" not in data, f"Found leaked password field in: {data}"
        for value in data.values():
            assert_no_password_key(value)
    elif isinstance(data, list):
        for item in data:
            assert_no_password_key(item)


# ==============================================================================
# 5.2 Required tests — review CRUD
# ==============================================================================

def test_review_create_and_list(db, client):
    # Seed a location
    loc = Location(content_id="loc_test_1", content_type_id="12", category="tourist_spot", title="테스트 장소", l_dong_signgu_cd="110", sigungu_name="종로구")
    db.add(loc)
    db.commit()
    db.refresh(loc)

    # 1. Create a review with a nickname
    payload = {"nickname": "리뷰어1", "content": "좋아요", "password": "pass"}
    resp = client.post(f"/api/locations/{loc.id}/reviews", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["nickname"] == "리뷰어1"
    assert data["content"] == "좋아요"
    assert "id" in data
    assert_no_password_key(data)

    # List reviews and check nickname matches
    resp = client.get(f"/api/locations/{loc.id}/reviews")
    assert resp.status_code == 200
    list_data = resp.json()
    assert len(list_data["items"]) == 1
    assert list_data["items"][0]["nickname"] == "리뷰어1"
    assert_no_password_key(list_data)


def test_review_nickname_normalization(db, client):
    loc = Location(content_id="loc_test_2", content_type_id="12", category="tourist_spot", title="테스트 장소", l_dong_signgu_cd="110", sigungu_name="종로구")
    db.add(loc)
    db.commit()
    db.refresh(loc)

    # Create review with nickname: null
    payload_null = {"nickname": None, "content": "내용1", "password": "pass"}
    resp = client.post(f"/api/locations/{loc.id}/reviews", json=payload_null)
    assert resp.status_code == 201
    assert resp.json()["nickname"] == "익명"

    # Create review with nickname: ""
    payload_empty = {"nickname": "", "content": "내용2", "password": "pass"}
    resp = client.post(f"/api/locations/{loc.id}/reviews", json=payload_empty)
    assert resp.status_code == 201
    assert resp.json()["nickname"] == "익명"

    # Verify database directly stores NULL (None) for both
    db_reviews = db.query(Review).all()
    assert len(db_reviews) == 2
    assert db_reviews[0].nickname is None
    assert db_reviews[1].nickname is None

    # Verify listing displays "익명"
    resp = client.get(f"/api/locations/{loc.id}/reviews")
    items = resp.json()["items"]
    assert items[0]["nickname"] == "익명"
    assert items[1]["nickname"] == "익명"


def test_review_validation_errors(db, client):
    loc = Location(content_id="loc_test_3", content_type_id="12", category="tourist_spot", title="테스트 장소", l_dong_signgu_cd="110", sigungu_name="종로구")
    db.add(loc)
    db.commit()

    # Empty content -> 422
    resp = client.post(f"/api/locations/{loc.id}/reviews", json={"nickname": "익명", "content": "", "password": "pass"})
    assert resp.status_code == 422

    # Non-existent location -> 404
    resp = client.post("/api/locations/9999/reviews", json={"nickname": "익명", "content": "내용", "password": "pass"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "LOCATION_NOT_FOUND"


def test_review_verify_password(db, client):
    loc = Location(content_id="loc_test_4", content_type_id="12", category="tourist_spot", title="테스트 장소", l_dong_signgu_cd="110", sigungu_name="종로구")
    db.add(loc)
    db.commit()
    
    review = Review(location_id=loc.id, nickname="익명", content="내용", password="testpassword")
    db.add(review)
    db.commit()

    # 1. Correct password -> 200, true
    resp = client.post(f"/api/reviews/{review.id}/verify", json={"password": "testpassword"})
    assert resp.status_code == 200
    assert resp.json()["verified"] is True

    # 2. Wrong password -> 200, false (assert 200, not 403!)
    resp = client.post(f"/api/reviews/{review.id}/verify", json={"password": "wrongpassword"})
    assert resp.status_code == 200
    assert resp.json()["verified"] is False

    # 3. Nonexistent review -> 404
    resp = client.post("/api/reviews/9999/verify", json={"password": "testpassword"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "REVIEW_NOT_FOUND"


def test_review_update(db, client):
    loc = Location(content_id="loc_test_5", content_type_id="12", category="tourist_spot", title="테스트 장소", l_dong_signgu_cd="110", sigungu_name="종로구")
    db.add(loc)
    db.commit()

    review = Review(location_id=loc.id, nickname="익명", content="오리지널", password="pass")
    db.add(review)
    db.commit()

    # Correct update -> 200
    resp = client.put(f"/api/reviews/{review.id}", json={"nickname": "수정자", "content": "수정됨", "password": "pass"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["nickname"] == "수정자"
    assert data["content"] == "수정됨"
    assert data["updated_at"] is not None
    assert_no_password_key(data)

    # Wrong password update -> 403
    resp = client.put(f"/api/reviews/{review.id}", json={"nickname": "해커", "content": "해킹시도", "password": "wrong"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "REVIEW_PASSWORD_MISMATCH"
    
    # Assert DB is unchanged
    db.refresh(review)
    assert review.nickname == "수정자"
    assert review.content == "수정됨"


def test_review_delete(db, client):
    loc = Location(content_id="loc_test_6", content_type_id="12", category="tourist_spot", title="테스트 장소", l_dong_signgu_cd="110", sigungu_name="종로구")
    db.add(loc)
    db.commit()

    review = Review(location_id=loc.id, nickname="익명", content="삭제할래", password="pass")
    db.add(review)
    db.commit()

    # Wrong password delete -> 403
    resp = client.request("DELETE", f"/api/reviews/{review.id}", json={"password": "wrong"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "REVIEW_PASSWORD_MISMATCH"
    assert db.query(Review).filter(Review.id == review.id).first() is not None

    # Correct password delete -> 204
    resp = client.request("DELETE", f"/api/reviews/{review.id}", json={"password": "pass"})
    assert resp.status_code == 204
    assert db.query(Review).filter(Review.id == review.id).first() is None


# ==============================================================================
# 5.3 Required tests — board rankings
# ==============================================================================

def test_board_rankings(db, client):
    # Seed locations
    # 3 distinct sigungus and 3 categories
    l1 = Location(id=101, content_id="l1", content_type_id="12", category="tourist_spot", title="A_Spot", l_dong_signgu_cd="110", sigungu_name="종로구")
    l2 = Location(id=102, content_id="l2", content_type_id="14", category="culture_facility", title="B_Spot", l_dong_signgu_cd="110", sigungu_name="종로구")
    l3 = Location(id=103, content_id="l3", content_type_id="15", category="festival", title="C_Spot", l_dong_signgu_cd="140", sigungu_name="중구")
    l4 = Location(id=104, content_id="l4", content_type_id="12", category="tourist_spot", title="D_Spot", l_dong_signgu_cd="140", sigungu_name="중구")
    l5 = Location(id=105, content_id="l5", content_type_id="38", category="shopping", title="E_Spot", l_dong_signgu_cd="680", sigungu_name="강남구")
    # l6: fewer than 5 games
    l6 = Location(id=106, content_id="l6", content_type_id="12", category="tourist_spot", title="F_Spot", l_dong_signgu_cd="680", sigungu_name="강남구")

    for l in [l1, l2, l3, l4, l5, l6]:
        db.add(l)
    db.commit()

    # Manually insert match game stats
    # l1: 6 games, 5 wins, 2 final appearances, 2 championships
    # l2: 5 games, 2 wins, 1 final appearance, 0 championships
    # l3: 5 games, 1 win, 0 final appearances, 0 championships
    # l4: 8 games, 4 wins, 2 final appearances, 1 championship
    # l5: 5 games, 3 wins, 1 final appearance, 1 championship
    # l6: 3 games (under 5 minimum), 2 wins, 0 final appearances
    
    # helper to add finished game
    def add_game(loc_a_id, loc_b_id, winner_id, is_final=False):
        g = MatchGame(
            match_id=1,
            round_no=1,
            order_in_round=0,
            location_a_id=loc_a_id,
            location_b_id=loc_b_id,
            winner_id=winner_id,
            is_final=is_final,
            completed_at=datetime.utcnow()
        )
        db.add(g)

    # l1 games (6 games, 5 wins, 2 finals, 2 championships)
    # final 1: l1 vs l2, winner l1
    add_game(101, 102, 101, is_final=True)
    # final 2: l1 vs l4, winner l1
    add_game(101, 104, 101, is_final=True)
    # others:
    add_game(101, 103, 101)
    add_game(101, 105, 101)
    add_game(101, 106, 101)
    add_game(101, 105, 105) # l1 loss to l5
    
    # l2 games (5 games, 2 wins, 1 final, 0 champ)
    # final: l1 vs l2, winner l1 (already added)
    add_game(102, 103, 102)
    add_game(102, 104, 102)
    add_game(102, 105, 105)
    add_game(102, 106, 106)
    
    # l3 games (5 games, 1 win, 0 final)
    # l1 vs l3, winner l1 (already added)
    # l2 vs l3, winner l2 (already added)
    add_game(103, 104, 103)
    add_game(103, 105, 105)
    add_game(103, 106, 106)
    
    # l4 games (7 games, 3 wins, 2 finals, 1 champ)
    # final 1: l1 vs l4, winner l1 (already added)
    # final 2: l4 vs l5, winner l4
    add_game(104, 105, 104, is_final=True)
    # l2 vs l4, winner l2 (already added)
    # l3 vs l4, winner l3 (already added)
    add_game(104, 102, 104)
    add_game(104, 103, 104)
    add_game(104, 105, 105)
    
    # l5 games (5 games, 3 wins, 1 final, 1 champ)
    # final: l4 vs l5, winner l4 (already added)
    # others:
    # l1 vs l5, winner l5 (already added)
    # l1 vs l5, winner l1 (already added)
    # l2 vs l5, winner l5 (already added)
    # l3 vs l5, winner l5 (already added)
    # l4 vs l5, winner l5 (already added)
    # l5 wins count: vs l1 (1), vs l2 (1), vs l3 (1), vs l4 (1). total wins = 4?
    # Let's count l5 games specifically from above:
    # 1. l1(winner) vs l5 (l1 win)
    # 2. l1 vs l5(winner) (l5 win)
    # 3. l2 vs l5(winner) (l5 win)
    # 4. l3 vs l5(winner) (l5 win)
    # 5. l4 vs l5(winner) (l5 win) (wait, l4 final was: l4 vs l5, winner l4 -> l4 win)
    # Let's count:
    # l5 has:
    # - l1 vs l5, winner l1 (loss)
    # - l1 vs l5, winner l5 (win)
    # - l2 vs l5, winner l5 (win)
    # - l3 vs l5, winner l5 (win)
    # - l4 vs l5, winner l4 (loss, final)
    # Total games: 5. Wins: 3. Finals: 1. Championships: 0.
    
    # l6 games:
    # l1 vs l6 (winner l1)
    # l2 vs l6 (winner l6)
    # l3 vs l6 (winner l6)
    # Total games = 3.

    db.commit()

    # Hand-computed rates:
    # l1: total=6, wins=5 (win_rate=5/6=0.8333), finals=2, champs=2 (championship_rate=2/2=1.0)
    # l2: total=5, wins=2 (win_rate=2/5=0.4000), finals=1, champs=0 (championship_rate=0/1=0.0)
    # l3: total=5, wins=1 (win_rate=1/5=0.2000), finals=0, champs=0 (championship_rate=0.0)
    # l4: total=7, wins=3 (win_rate=3/7=0.4286), finals=2, champs=1 (championship_rate=1/2=0.5)
    # l5: total=5, wins=3 (win_rate=3/5=0.6000), finals=1, champs=0 (championship_rate=0.0)
    # l6: total=3 (excluded because < 5)

    # 1. Verify sort=championship_rate
    resp = client.get("/api/board/rankings?sort=championship_rate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sort"] == "championship_rate"
    
    # Excludes l6 (total_games < 5) and l3 (final_appearances == 0)
    # Expected order: l1 (ch_rate=1.0), l4 (ch_rate=0.5), l2 (ch_rate=0.0), l5 (ch_rate=0.0)
    # Note on l2 vs l5 tie: Both ch_rate=0.0, both championships=0. 
    # Title tie-breaker: B_Spot (l2) vs E_Spot (l5). B_Spot ranks first.
    items = data["items"]
    assert len(items) == 4
    
    assert items[0]["location"]["id"] == 101
    assert pytest.approx(items[0]["championship_rate"]) == 1.0
    assert pytest.approx(items[0]["win_rate"]) == 0.8333
    
    assert items[1]["location"]["id"] == 104
    assert pytest.approx(items[1]["championship_rate"]) == 0.5
    
    assert items[2]["location"]["id"] == 102
    assert items[3]["location"]["id"] == 105
    
    # 2. Verify sort=win_rate
    resp = client.get("/api/board/rankings?sort=win_rate")
    assert resp.status_code == 200
    data_win = resp.json()
    
    # l3 is included here because it has 5 games (though 0 finals)
    # Expected order: l1 (0.8333), l5 (0.6000), l4 (0.5000), l2 (0.4000), l3 (0.2000)
    items_win = data_win["items"]
    assert len(items_win) == 5
    
    assert items_win[0]["location"]["id"] == 101
    assert items_win[1]["location"]["id"] == 105
    assert items_win[2]["location"]["id"] == 104
    assert items_win[3]["location"]["id"] == 102
    assert items_win[4]["location"]["id"] == 103

    # 3. Verify filters (AND condition)
    # regions="110" (종로구) and categories="tourist_spot"
    # locations in 110: l1, l2. categories: l1=tourist_spot, l2=culture_facility.
    # So intersection should only have l1.
    resp = client.get("/api/board/rankings?regions=110&categories=tourist_spot")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["location"]["id"] == 101

    # 4. Verify pagination
    resp = client.get("/api/board/rankings?sort=win_rate&page=1&size=2")
    assert resp.status_code == 200
    page1 = resp.json()
    assert page1["total"] == 5
    assert page1["total_pages"] == 3
    assert len(page1["items"]) == 2
    assert page1["items"][0]["location"]["id"] == 101
    assert page1["items"][1]["location"]["id"] == 105

    resp = client.get("/api/board/rankings?sort=win_rate&page=2&size=2")
    assert resp.status_code == 200
    page2 = resp.json()
    assert len(page2["items"]) == 2
    assert page2["items"][0]["location"]["id"] == 104
    assert page2["items"][1]["location"]["id"] == 102


# ==============================================================================
# 5.4 Required test — end domain
# ==============================================================================

def test_end_domain_winner_lookup(db, client):
    # Seed 2 locations
    loc1 = Location(id=201, content_id="loc_end_1", content_type_id="12", category="tourist_spot", title="A_End", l_dong_signgu_cd="110", sigungu_name="종로구")
    loc2 = Location(id=202, content_id="loc_end_2", content_type_id="12", category="tourist_spot", title="B_End", l_dong_signgu_cd="110", sigungu_name="종로구")
    db.add(loc1)
    db.add(loc2)
    db.commit()

    # Create match still in_progress
    match = Match(id=501, total_rounds=4, status="in_progress", created_at=datetime.utcnow())
    db.add(match)
    db.commit()

    # 1. Result on match in_progress -> 409
    resp = client.get("/api/matches/501/result")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "MATCH_NOT_FINISHED"

    # 2. Result on unknown match -> 404
    resp = client.get("/api/matches/9999/result")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "MATCH_NOT_FOUND"

    # Set match to finished and add final game with winner
    match.status = "finished"
    match.finished_at = datetime.utcnow()
    
    final_game = MatchGame(
        match_id=501,
        round_no=2,
        order_in_round=0,
        location_a_id=201,
        location_b_id=202,
        winner_id=201,
        is_final=True,
        completed_at=datetime.utcnow()
    )
    db.add(final_game)
    db.commit()

    # 3. Correct winner lookup -> 200
    resp = client.get("/api/matches/501/result")
    assert resp.status_code == 200
    data = resp.json()
    assert data["match_id"] == 501
    assert data["winner_location"]["id"] == 201
    assert data["winner_location"]["title"] == "A_End"
    assert data["finished_at"] is not None


# ==============================================================================
# 5.5 Integration smoke test — the full cross-domain flow
# ==============================================================================

def test_full_integration_smoke_flow(db, client):
    # 1. Seed 4 locations
    locations = [
        Location(id=301, content_id="s1", content_type_id="12", category="tourist_spot", title="Spot_1", l_dong_signgu_cd="110", sigungu_name="종로구"),
        Location(id=302, content_id="s2", content_type_id="12", category="tourist_spot", title="Spot_2", l_dong_signgu_cd="110", sigungu_name="종로구"),
        Location(id=303, content_id="s3", content_type_id="12", category="tourist_spot", title="Spot_3", l_dong_signgu_cd="110", sigungu_name="종로구"),
        Location(id=304, content_id="s4", content_type_id="12", category="tourist_spot", title="Spot_4", l_dong_signgu_cd="110", sigungu_name="종로구"),
    ]
    for loc in locations:
        db.add(loc)
    db.commit()

    # 2. GET candidates
    resp = client.get("/api/locations/candidates?regions=110&categories=tourist_spot")
    assert resp.status_code == 200
    assert resp.json()["candidate_count"] == 4
    assert resp.json()["available_rounds"] == [4]

    # 3. Create match
    resp = client.post("/api/matches", json={"regions": ["110"], "categories": ["tourist_spot"], "total_rounds": 4})
    assert resp.status_code == 201
    match_data = resp.json()
    match_id = match_data["match_id"]

    # 4. Play games until final result
    # We will query match details to see current active game
    for _ in range(3):  # 4 rounds require 3 games (2 in round 1, 1 final)
        resp = client.get(f"/api/matches/{match_id}")
        assert resp.status_code == 200
        state = resp.json()
        game = state["current_game"]
        
        # Post winner (always location_a)
        winner_id = game["location_a"]["id"]
        resp = client.post(
            f"/api/matches/{match_id}/games/{game['id']}/result",
            json={"winner_id": winner_id}
        )
        assert resp.status_code == 200
        outcome = resp.json()
        if outcome["is_final_result"]:
            winner_location_id = outcome["winner_location_id"]
            break

    # 5. GET final result
    resp = client.get(f"/api/matches/{match_id}/result")
    assert resp.status_code == 200
    res_data = resp.json()
    winner_id = res_data["winner_location"]["id"]
    assert winner_id == winner_location_id

    # 6. POST a review for winner
    review_payload = {
        "nickname": "통합러버",
        "content": "이곳이 바로 우승지!",
        "password": "finalpassword"
    }
    resp = client.post(f"/api/locations/{winner_id}/reviews", json=review_payload)
    assert resp.status_code == 201
    review_id = resp.json()["id"]

    # 7. GET reviews list
    resp = client.get(f"/api/locations/{winner_id}/reviews")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["content"] == "이곳이 바로 우승지!"

    # 8. PUT review
    resp = client.put(
        f"/api/reviews/{review_id}",
        json={"nickname": "수정닉", "content": "완전최고!", "password": "finalpassword"}
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "완전최고!"

    # DELETE review
    resp = client.request("DELETE", f"/api/reviews/{review_id}", json={"password": "finalpassword"})
    assert resp.status_code == 204

    # Confirm it is gone
    resp = client.get(f"/api/locations/{winner_id}/reviews")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 0

    # 9. GET board rankings - should be empty because none of locations have >= 5 total_games yet.
    resp = client.get("/api/board/rankings")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 0
