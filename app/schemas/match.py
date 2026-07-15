from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from app.schemas.location import LocationResponse


class MatchCreateRequest(BaseModel):
    regions: List[str] = Field(..., min_length=1)
    categories: List[str] = Field(..., min_length=1)
    total_rounds: Literal[4, 8, 16, 32, 64]


class GameResponse(BaseModel):
    id: int
    round_no: int
    order_in_round: int
    location_a: LocationResponse
    location_b: LocationResponse

    class Config:
        from_attributes = True


class MatchCreateResponse(BaseModel):
    match_id: int
    total_rounds: int
    status: str
    current_round_no: int
    total_round_count: int
    first_game: GameResponse


class MatchStateResponse(BaseModel):
    match_id: int
    total_rounds: int
    status: str
    current_round_no: int
    total_round_count: int
    round_display: str
    current_game: GameResponse


class GameResultRequest(BaseModel):
    winner_id: int


class GameResultResponse(BaseModel):
    is_final_result: bool
    status: str
    next_game: Optional[GameResponse] = None
    winner_location_id: Optional[int] = None


class MatchResultResponse(BaseModel):
    match_id: int
    winner: LocationResponse
