import math
import random
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.models.location import Location
from app.models.match import Match, MatchFilter, MatchGame


# Custom Exception Classes for Route Handler translation
class RoundExceedsCandidatesError(Exception):
    def __init__(self, requested: int, actual: int):
        self.requested = requested
        self.actual = actual
        super().__init__(f"Requested round count {requested} exceeds actual candidate count {actual}")


class LocationNotFoundError(Exception):
    pass


class MatchNotFoundError(Exception):
    pass


class MatchAlreadyFinishedError(Exception):
    def __init__(self, match_id: int):
        self.match_id = match_id
        super().__init__(f"Match {match_id} is already finished")


class MatchNotFinishedError(Exception):
    pass


class GameNotFoundError(Exception):
    pass


class GameAlreadyCompletedError(Exception):
    pass


class InvalidWinnerError(Exception):
    pass


def get_candidate_locations(db: Session, regions: List[str], categories: List[str]) -> List[Location]:
    """Filter locations by regions and categories.
    
    If 'ALL' is in the regions list, do not filter by region.
    If 'ALL' is in the categories list, do not filter by category.
    """
    if not regions or not categories:
        return []

    query = select(Location)
    filters = []

    if "ALL" not in regions:
        filters.append(Location.l_dong_signgu_cd.in_(regions))

    if "ALL" not in categories:
        filters.append(Location.category.in_(categories))

    if filters:
        query = query.where(and_(*filters))

    return list(db.scalars(query).all())


def compute_available_rounds(candidate_count: int) -> List[int]:
    """Return available round configurations [4, 8, 16, 32, 64] that are <= candidate_count."""
    ROUND_OPTIONS = [4, 8, 16, 32, 64]
    return [r for r in ROUND_OPTIONS if r <= candidate_count]


def create_match(db: Session, regions: List[str], categories: List[str], total_rounds: int) -> Match:
    """Create a match, store its filters, randomly sample candidates, and pair them for round 1."""
    # 1. Filter candidates
    candidates = get_candidate_locations(db, regions, categories)
    
    # 2. Check candidate count
    if len(candidates) < total_rounds:
        raise RoundExceedsCandidatesError(requested=total_rounds, actual=len(candidates))

    # 3. Randomly sample candidates
    sampled = random.sample(candidates, total_rounds)

    # 4. Create Match row
    match = Match(
        total_rounds=total_rounds,
        status="in_progress",
        created_at=datetime.utcnow()
    )
    db.add(match)
    db.flush()  # Populates match.id

    # 5. Create MatchFilter rows
    if "ALL" in regions:
        db.add(MatchFilter(match_id=match.id, filter_type="region", filter_value="ALL", is_all=True))
    else:
        for r in regions:
            db.add(MatchFilter(match_id=match.id, filter_type="region", filter_value=r, is_all=False))

    if "ALL" in categories:
        db.add(MatchFilter(match_id=match.id, filter_type="category", filter_value="ALL", is_all=True))
    else:
        for c in categories:
            db.add(MatchFilter(match_id=match.id, filter_type="category", filter_value=c, is_all=False))

    # 6. Pair up candidates for Round 1
    num_games = total_rounds // 2
    for i in range(num_games):
        loc_a = sampled[2 * i]
        loc_b = sampled[2 * i + 1]
        db.add(MatchGame(
            match_id=match.id,
            round_no=1,
            order_in_round=i,
            location_a_id=loc_a.id,
            location_b_id=loc_b.id,
            winner_id=None,
            is_final=False
        ))

    db.commit()
    db.refresh(match)
    return match


def get_match_state(db: Session, match_id: int) -> Dict[str, Any]:
    """Retrieve current in-progress match state, including the active game and round_display string."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise MatchNotFoundError()

    if match.status == "finished":
        raise MatchAlreadyFinishedError(match_id)

    # Find the incomplete game with the lowest (round_no, order_in_round)
    current_game = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.winner_id == None
    ).order_by(
        MatchGame.round_no.asc(),
        MatchGame.order_in_round.asc()
    ).first()

    if not current_game:
        raise GameNotFoundError()

    N = match.total_rounds // (2 ** (current_game.round_no - 1))
    M = current_game.order_in_round + 1
    round_display = f"{N}강 {M}번째 경기"
    total_round_count = int(math.log2(match.total_rounds))

    return {
        "match_id": match.id,
        "total_rounds": match.total_rounds,
        "status": match.status,
        "current_round_no": current_game.round_no,
        "total_round_count": total_round_count,
        "round_display": round_display,
        "current_game": current_game
    }


def record_game_result(db: Session, match_id: int, game_id: int, winner_id: int) -> Dict[str, Any]:
    """Record game winner, check round completion, and handle lazy generation of next round or final result."""
    # 1. Fetch match
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise MatchNotFoundError()

    if match.status == "finished":
        raise MatchAlreadyFinishedError(match_id)

    # 2. Fetch game
    game = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.id == game_id
    ).first()
    if not game:
        raise GameNotFoundError()

    # 3. Check if already completed
    if game.winner_id is not None:
        raise GameAlreadyCompletedError()

    # 4. Check if winner_id is valid
    if winner_id not in (game.location_a_id, game.location_b_id):
        raise InvalidWinnerError()

    # Record result
    game.winner_id = winner_id
    game.completed_at = datetime.utcnow()
    db.flush()

    # 5. Check whether the current round is fully complete
    current_round_no = game.round_no
    round_games = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.round_no == current_round_no
    ).all()

    incomplete_games = [g for g in round_games if g.winner_id is None]

    if incomplete_games:
        # Case A: round not yet complete
        incomplete_games.sort(key=lambda g: g.order_in_round)
        next_game = incomplete_games[0]
        db.commit()
        return {
            "is_final_result": False,
            "status": "in_progress",
            "next_game": next_game,
            "winner_location_id": None
        }

    # Round just completed. Check if it was the final round.
    if game.is_final or len(round_games) == 1:
        # Case B: round just completed, and it was the final
        match.status = "finished"
        match.finished_at = datetime.utcnow()
        db.commit()
        return {
            "is_final_result": True,
            "status": "finished",
            "next_game": None,
            "winner_location_id": winner_id
        }

    # Case C: round just completed, but it was not the final. Advance to next round.
    # Collect winners in order_in_round ascending order
    round_games.sort(key=lambda g: g.order_in_round)
    winners = [g.winner_id for g in round_games]

    next_round_no = current_round_no + 1
    num_next_games = len(winners) // 2

    next_games = []
    for i in range(num_next_games):
        loc_a_id = winners[2 * i]
        loc_b_id = winners[2 * i + 1]
        
        # If the next round has exactly 1 game, it is the final
        is_final = (num_next_games == 1)

        new_game = MatchGame(
            match_id=match_id,
            round_no=next_round_no,
            order_in_round=i,
            location_a_id=loc_a_id,
            location_b_id=loc_b_id,
            winner_id=None,
            is_final=is_final
        )
        db.add(new_game)
        next_games.append(new_game)

    db.flush()
    db.commit()

    next_games.sort(key=lambda g: g.order_in_round)
    return {
        "is_final_result": False,
        "status": "in_progress",
        "next_game": next_games[0],
        "winner_location_id": None
    }


def get_match_result(db: Session, match_id: int) -> Dict[str, Any]:
    """Retrieve final match result with the winner's full location payload."""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise MatchNotFoundError()

    if match.status != "finished":
        raise MatchNotFinishedError()

    # Find the final game (the one with is_final=True)
    final_game = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.is_final == True
    ).first()

    if not final_game:
        # Fallback to the game with the highest round_no
        final_game = db.query(MatchGame).filter(
            MatchGame.match_id == match_id
        ).order_by(
            MatchGame.round_no.desc()
        ).first()

    if not final_game or final_game.winner_id is None:
        raise MatchNotFinishedError()

    winner = db.query(Location).filter(Location.id == final_game.winner_id).first()
    if not winner:
        raise LocationNotFoundError()

    return {
        "match_id": match.id,
        "winner": winner
    }
