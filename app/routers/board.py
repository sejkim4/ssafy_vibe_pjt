import math
from typing import List, Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.schemas.board import BoardRankingResponse, BoardRankingItem
from app.services import board_service

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/board/rankings", response_model=BoardRankingResponse)
def get_rankings(
    sort: Literal["championship_rate", "win_rate"] = "championship_rate",
    regions: List[str] = Query(default=[]),
    categories: List[str] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> BoardRankingResponse:
    items, total = board_service.get_board_rankings(
        db=db,
        sort=sort,
        regions=regions,
        categories=categories,
        page=page,
        size=size,
    )
    
    total_pages = math.ceil(total / size) if total > 0 else 0
    
    # Mapping items to BoardRankingItem structure
    ranking_items = []
    for item in items:
        ranking_items.append(BoardRankingItem.model_validate(item))
        
    return BoardRankingResponse(
        sort=sort,
        items=ranking_items,
        page=page,
        size=size,
        total=total,
        total_pages=total_pages,
    )
