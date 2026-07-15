import math
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.schemas.location import LocationResponse
from app.schemas.match import (
    MatchCreateRequest,
    MatchCreateResponse,
    MatchStateResponse,
    GameResponse,
    GameResultRequest,
    GameResultResponse,
    MatchResultResponse,
)
from app.services import match_service
from app.services.match_service import (
    RoundExceedsCandidatesError,
    MatchNotFoundError,
    MatchAlreadyFinishedError,
    MatchNotFinishedError,
    GameNotFoundError,
    GameAlreadyCompletedError,
    InvalidWinnerError,
    LocationNotFoundError,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/matches", response_model=MatchCreateResponse, status_code=210)  # Standard is 201 Created but let's mount it, wait, requirements spec mentions 201 Created. Let's return 201 status code!
# Let's set status_code=201
@router.post("/matches", response_model=MatchCreateResponse, status_code=201)
def create_new_match(
    request: MatchCreateRequest, db: Session = Depends(get_db)
) -> MatchCreateResponse:
    try:
        match = match_service.create_match(
            db=db,
            regions=request.regions,
            categories=request.categories,
            total_rounds=request.total_rounds,
        )
        
        first_game = None
        for game in match.games:
            if game.round_no == 1 and game.order_in_round == 0:
                first_game = game
                break
                
        if not first_game:
            raise HTTPException(
                status_code=500,
                detail={"error_code": "INTERNAL_SERVER_ERROR", "message": "First game not generated"},
            )
            
        total_round_count = int(math.log2(match.total_rounds))
        
        return MatchCreateResponse(
            match_id=match.id,
            total_rounds=match.total_rounds,
            status=match.status,
            current_round_no=1,
            total_round_count=total_round_count,
            first_game=GameResponse.model_validate(first_game),
        )
    except RoundExceedsCandidatesError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ROUND_EXCEEDS_CANDIDATES",
                "message": f"Requested round count {e.requested} exceeds actual candidate count {e.actual}.",
            },
        )


@router.get("/matches/{match_id}", response_model=MatchStateResponse)
def get_match(match_id: int, db: Session = Depends(get_db)) -> MatchStateResponse:
    try:
        state = match_service.get_match_state(db, match_id)
        return MatchStateResponse(
            match_id=state["match_id"],
            total_rounds=state["total_rounds"],
            status=state["status"],
            current_round_no=state["current_round_no"],
            total_round_count=state["total_round_count"],
            round_display=state["round_display"],
            current_game=GameResponse.model_validate(state["current_game"]),
        )
    except MatchNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "MATCH_NOT_FOUND", "message": f"Match {match_id} not found"},
        )
    except MatchAlreadyFinishedError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "MATCH_ALREADY_FINISHED",
                "message": f"Match {match_id} already finished",
                "redirect_to": f"/worldcup/{e.match_id}/result",
            },
        )
    except GameNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "GAME_NOT_FOUND", "message": "No active games found for this match"},
        )


@router.post("/matches/{match_id}/games/{game_id}/result", response_model=GameResultResponse)
def post_game_result(
    match_id: int,
    game_id: int,
    request: GameResultRequest,
    db: Session = Depends(get_db),
) -> GameResultResponse:
    try:
        outcome = match_service.record_game_result(
            db=db,
            match_id=match_id,
            game_id=game_id,
            winner_id=request.winner_id,
        )
        
        next_game_resp = None
        if outcome["next_game"]:
            next_game_resp = GameResponse.model_validate(outcome["next_game"])
            
        return GameResultResponse(
            is_final_result=outcome["is_final_result"],
            status=outcome["status"],
            next_game=next_game_resp,
            winner_location_id=outcome["winner_location_id"],
        )
    except MatchNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "MATCH_NOT_FOUND", "message": f"Match {match_id} not found"},
        )
    except MatchAlreadyFinishedError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "MATCH_ALREADY_FINISHED",
                "message": f"Match {match_id} already finished",
                "redirect_to": f"/worldcup/{e.match_id}/result",
            },
        )
    except GameNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "GAME_NOT_FOUND", "message": f"Game {game_id} not found in match {match_id}"},
        )
    except GameAlreadyCompletedError:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "GAME_ALREADY_COMPLETED", "message": "Winner already recorded for this game"},
        )
    except InvalidWinnerError:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_WINNER",
                "message": f"Winner ID {request.winner_id} is not a valid participant in this game",
            },
        )


@router.get("/matches/{match_id}/result", response_model=MatchResultResponse)
def get_final_result(match_id: int, db: Session = Depends(get_db)) -> MatchResultResponse:
    try:
        res = match_service.get_match_result(db, match_id)
        return MatchResultResponse(
            match_id=res["match_id"],
            winner=LocationResponse.model_validate(res["winner"]),
        )
    except MatchNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "MATCH_NOT_FOUND", "message": f"Match {match_id} not found"},
        )
    except MatchNotFinishedError:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "MATCH_NOT_FINISHED", "message": "Match is not finished yet"},
        )
    except LocationNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": "Winner location details not found"},
        )
