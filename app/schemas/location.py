from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Optional, List


class LocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_id: str
    content_type_id: str
    category: str
    title: str
    addr1: Optional[str] = None
    map_x: Optional[float] = None
    map_y: Optional[float] = None
    first_image: Optional[str] = None
    l_dong_signgu_cd: str
    sigungu_name: str
    lcls_systm_1: Optional[str] = None
    lcls_systm_2: Optional[str] = None
    lcls_systm_3: Optional[str] = None
    created_at: datetime


class CandidatesResponse(BaseModel):
    candidate_count: int
    available_rounds: List[int]


class MetaItem(BaseModel):
    code: str
    name: str


class MetaResponse(BaseModel):
    items: List[MetaItem]
