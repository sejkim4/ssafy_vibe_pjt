from pydantic import BaseModel
from typing import List, Optional


class BoardLocationResponse(BaseModel):
    id: int
    title: str
    category: str
    category_name: str
    first_image: Optional[str] = None

    class Config:
        from_attributes = True


class BoardRankingItem(BaseModel):
    rank: int
    location: BoardLocationResponse
    championship_rate: float
    win_rate: float
    total_games: int
    championships: int
    final_appearances: int


class BoardRankingResponse(BaseModel):
    sort: str
    items: List[BoardRankingItem]
    page: int
    size: int
    total: int
    total_pages: int
