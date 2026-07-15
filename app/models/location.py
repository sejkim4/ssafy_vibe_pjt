from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Location(Base):
    """TourAPI location row.

    Category values are derived from content_type_id:
    12=tourist_spot, 14=culture_facility, 15=festival,
    28=leports, 32=accommodation, 38=shopping.
    """

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    content_type_id: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    addr1: Mapped[str | None] = mapped_column(String, nullable=True)
    map_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    map_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_image: Mapped[str | None] = mapped_column(String, nullable=True)
    l_dong_signgu_cd: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sigungu_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    lcls_systm_1: Mapped[str | None] = mapped_column(String, nullable=True)
    lcls_systm_2: Mapped[str | None] = mapped_column(String, nullable=True)
    lcls_systm_3: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    reviews = relationship("Review", back_populates="location")
