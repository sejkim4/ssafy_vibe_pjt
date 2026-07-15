import math
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.schemas.review import (
    ReviewCreateRequest,
    ReviewCreateResponse,
    ReviewUpdateRequest,
    ReviewUpdateResponse,
    ReviewListItem,
    ReviewListResponse,
    ReviewVerifyRequest,
    ReviewVerifyResponse,
    ReviewDeleteRequest,
)
from app.services import review_service
from app.services.review_service import (
    LocationNotFoundError,
    ReviewNotFoundError,
    ReviewPasswordMismatchError,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def normalize_nickname(nickname: str | None) -> str:
    """Normalize None or empty string to '익명' for API output."""
    if not nickname or nickname.strip() == "":
        return "익명"
    return nickname


@router.get("/locations/{location_id}/reviews", response_model=ReviewListResponse)
def get_location_reviews(
    location_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ReviewListResponse:
    reviews, total = review_service.list_reviews(db, location_id, page, size)
    
    items = []
    for r in reviews:
        items.append(
            ReviewListItem(
                id=r.id,
                nickname=normalize_nickname(r.nickname),
                content=r.content,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
        
    total_pages = math.ceil(total / size) if total > 0 else 0
    
    return ReviewListResponse(
        items=items,
        page=page,
        size=size,
        total=total,
        total_pages=total_pages,
    )


@router.post("/locations/{location_id}/reviews", response_model=ReviewCreateResponse, status_code=201)
def create_location_review(
    location_id: int,
    request: ReviewCreateRequest,
    db: Session = Depends(get_db),
) -> ReviewCreateResponse:
    try:
        r = review_service.create_review(
            db=db,
            location_id=location_id,
            nickname=request.nickname,
            content=request.content,
            password=request.password,
        )
        return ReviewCreateResponse(
            id=r.id,
            location_id=r.location_id,
            nickname=normalize_nickname(r.nickname),
            content=r.content,
            created_at=r.created_at,
        )
    except LocationNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "LOCATION_NOT_FOUND", "message": f"Location {location_id} not found"},
        )


@router.post("/reviews/{review_id}/verify", response_model=ReviewVerifyResponse)
def verify_review_password(
    review_id: int,
    request: ReviewVerifyRequest,
    db: Session = Depends(get_db),
) -> ReviewVerifyResponse:
    try:
        verified = review_service.verify_password(db, review_id, request.password)
        return ReviewVerifyResponse(verified=verified)
    except ReviewNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "REVIEW_NOT_FOUND", "message": f"Review {review_id} not found"},
        )


@router.put("/reviews/{review_id}", response_model=ReviewUpdateResponse)
def update_review_content(
    review_id: int,
    request: ReviewUpdateRequest,
    db: Session = Depends(get_db),
) -> ReviewUpdateResponse:
    try:
        r = review_service.update_review(
            db=db,
            review_id=review_id,
            nickname=request.nickname,
            content=request.content,
            password=request.password,
        )
        return ReviewUpdateResponse(
            id=r.id,
            location_id=r.location_id,
            nickname=normalize_nickname(r.nickname),
            content=r.content,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
    except ReviewNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "REVIEW_NOT_FOUND", "message": f"Review {review_id} not found"},
        )
    except ReviewPasswordMismatchError:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "REVIEW_PASSWORD_MISMATCH", "message": "Incorrect password"},
        )


@router.delete("/reviews/{review_id}", status_code=204)
def delete_review_content(
    review_id: int,
    request: ReviewDeleteRequest,
    db: Session = Depends(get_db),
):
    try:
        review_service.delete_review(db, review_id, request.password)
        return
    except ReviewNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "REVIEW_NOT_FOUND", "message": f"Review {review_id} not found"},
        )
    except ReviewPasswordMismatchError:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "REVIEW_PASSWORD_MISMATCH", "message": "Incorrect password"},
        )
