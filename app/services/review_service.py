from datetime import datetime
from typing import List, Tuple, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.review import Review
from app.models.location import Location


class LocationNotFoundError(Exception):
    pass


class ReviewNotFoundError(Exception):
    pass


class ReviewPasswordMismatchError(Exception):
    pass


def list_reviews(db: Session, location_id: int, page: int, size: int) -> Tuple[List[Review], int]:
    """Retrieve a paginated list of reviews for a given location, ordered by created_at desc."""
    # We do not raise 404 if the location does not exist per specification section 3.1
    # "If location_id doesn't exist, still return 200 with an empty items list rather than 404"
    
    total = db.query(func.count(Review.id)).filter(Review.location_id == location_id).scalar() or 0
    
    offset = (page - 1) * size
    reviews = db.query(Review).filter(
        Review.location_id == location_id
    ).order_by(
        Review.created_at.desc()
    ).offset(offset).limit(size).all()
    
    return reviews, total


def create_review(db: Session, location_id: int, nickname: Optional[str], content: str, password: str) -> Review:
    """Create a new review for a location. Normalizes empty nickname to None."""
    # Check if location exists
    location_exists = db.query(Location).filter(Location.id == location_id).first() is not None
    if not location_exists:
        raise LocationNotFoundError()

    # Normalize empty nickname to None
    normalized_nickname = nickname if nickname != "" else None

    # Plaintext storage intentional, for educational purposes.
    new_review = Review(
        location_id=location_id,
        nickname=normalized_nickname,
        content=content,
        password=password,
        created_at=datetime.utcnow()
    )
    db.add(new_review)
    db.commit()
    db.refresh(new_review)
    return new_review


def verify_password(db: Session, review_id: int, password: str) -> bool:
    """Check if the provided password matches the review's password."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise ReviewNotFoundError()

    # Plaintext comparison intentional, for educational purposes.
    return review.password == password


def update_review(db: Session, review_id: int, nickname: Optional[str], content: str, password: str) -> Review:
    """Update a review if password matches. Normalizes empty nickname to None."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise ReviewNotFoundError()

    # Plaintext comparison intentional, for educational purposes.
    if review.password != password:
        raise ReviewPasswordMismatchError()

    # Normalize empty nickname to None
    normalized_nickname = nickname if nickname != "" else None

    review.nickname = normalized_nickname
    review.content = content
    review.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(review)
    return review


def delete_review(db: Session, review_id: int, password: str) -> None:
    """Hard delete a review if password matches."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise ReviewNotFoundError()

    # Plaintext comparison intentional, for educational purposes.
    if review.password != password:
        raise ReviewPasswordMismatchError()

    db.delete(review)
    db.commit()
