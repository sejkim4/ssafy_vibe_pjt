from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.location import Location
from app.schemas.location import (
    LocationResponse,
    CandidatesResponse,
    MetaResponse,
    MetaItem,
)
from app.services import match_service

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


REGIONS_LIST = [
    {"code": "110", "name": "종로구"},
    {"code": "140", "name": "중구"},
    {"code": "170", "name": "용산구"},
    {"code": "200", "name": "성동구"},
    {"code": "215", "name": "광진구"},
    {"code": "230", "name": "동대문구"},
    {"code": "260", "name": "중랑구"},
    {"code": "290", "name": "성북구"},
    {"code": "305", "name": "강북구"},
    {"code": "320", "name": "도봉구"},
    {"code": "350", "name": "노원구"},
    {"code": "380", "name": "은평구"},
    {"code": "410", "name": "서대문구"},
    {"code": "440", "name": "마포구"},
    {"code": "470", "name": "양천구"},
    {"code": "500", "name": "강서구"},
    {"code": "530", "name": "구로구"},
    {"code": "545", "name": "금천구"},
    {"code": "560", "name": "영등포구"},
    {"code": "590", "name": "동작구"},
    {"code": "620", "name": "관악구"},
    {"code": "650", "name": "서초구"},
    {"code": "680", "name": "강남구"},
    {"code": "710", "name": "송파구"},
    {"code": "740", "name": "강동구"},
]

CATEGORIES_LIST = [
    {"code": "tourist_spot", "name": "관광지"},
    {"code": "culture_facility", "name": "문화시설"},
    {"code": "festival", "name": "축제·행사"},
    {"code": "leports", "name": "레포츠"},
    {"code": "accommodation", "name": "숙박"},
    {"code": "shopping", "name": "쇼핑"},
]


@router.get("/meta/regions", response_model=MetaResponse)
def get_regions() -> MetaResponse:
    return MetaResponse(items=[MetaItem(**item) for item in REGIONS_LIST])


@router.get("/meta/categories", response_model=MetaResponse)
def get_categories() -> MetaResponse:
    return MetaResponse(items=[MetaItem(**item) for item in CATEGORIES_LIST])


@router.get("/locations/candidates", response_model=CandidatesResponse)
def get_candidates(
    regions: List[str] = Query(..., min_length=1),
    categories: List[str] = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> CandidatesResponse:
    # Double check for empty list manually in case min_length didn't catch it
    if not regions or not categories:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": "regions and categories must not be empty",
            },
        )
    
    candidates = match_service.get_candidate_locations(db, regions, categories)
    candidate_count = len(candidates)
    available_rounds = match_service.compute_available_rounds(candidate_count)
    
    return CandidatesResponse(
        candidate_count=candidate_count,
        available_rounds=available_rounds
    )


@router.get("/locations/{location_id}", response_model=LocationResponse)
def get_location(location_id: int, db: Session = Depends(get_db)) -> LocationResponse:
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "LOCATION_NOT_FOUND",
                "message": f"Location {location_id} not found",
            },
        )
    return LocationResponse.model_validate(location)
