from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional


class ReviewCreateRequest(BaseModel):
    nickname: Optional[str] = None
    content: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ReviewCreateResponse(BaseModel):
    id: int
    location_id: int
    nickname: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewUpdateRequest(BaseModel):
    nickname: Optional[str] = None
    content: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ReviewUpdateResponse(BaseModel):
    id: int
    location_id: int
    nickname: str
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReviewListItem(BaseModel):
    id: int
    nickname: str
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReviewListResponse(BaseModel):
    items: List[ReviewListItem]
    page: int
    size: int
    total: int
    total_pages: int


class ReviewVerifyRequest(BaseModel):
    password: str = Field(..., min_length=1)


class ReviewVerifyResponse(BaseModel):
    verified: bool


class ReviewDeleteRequest(BaseModel):
    password: str = Field(..., min_length=1)
