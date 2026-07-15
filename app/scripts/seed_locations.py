import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update

from app.config import get_settings
from app.database import SessionLocal
from app.models.location import Location
from app.scripts.init_db import init_db

logger = logging.getLogger(__name__)

CATEGORY_FILES = [
    ("서울_관광지.json", "12", "tourist_spot", 783),
    ("서울_문화시설.json", "14", "culture_facility", 566),
    ("서울_축제공연행사.json", "15", "festival", 201),
    ("서울_레포츠.json", "28", "leports", 126),
    ("서울_숙박.json", "32", "accommodation", 423),
    ("서울_쇼핑.json", "38", "shopping", 4368),
]

DISTRICT_CODES = {
    "110": "Jongno-gu",
    "140": "Jung-gu",
    "170": "Yongsan-gu",
    "200": "Seongdong-gu",
    "215": "Gwangjin-gu",
    "230": "Dongdaemun-gu",
    "260": "Jungnang-gu",
    "290": "Seongbuk-gu",
    "305": "Gangbuk-gu",
    "320": "Dobong-gu",
    "350": "Nowon-gu",
    "380": "Eunpyeong-gu",
    "410": "Seodaemun-gu",
    "440": "Mapo-gu",
    "470": "Yangcheon-gu",
    "500": "Gangseo-gu",
    "530": "Guro-gu",
    "545": "Geumcheon-gu",
    "560": "Yeongdeungpo-gu",
    "590": "Dongjak-gu",
    "620": "Gwanak-gu",
    "650": "Seocho-gu",
    "680": "Gangnam-gu",
    "710": "Songpa-gu",
    "740": "Gangdong-gu",
}

DISTRICT_NAME_TO_CODE = {
    "종로구": "110",
    "중구": "140",
    "용산구": "170",
    "성동구": "200",
    "광진구": "215",
    "동대문구": "230",
    "중랑구": "260",
    "성북구": "290",
    "강북구": "305",
    "도봉구": "320",
    "노원구": "350",
    "은평구": "380",
    "서대문구": "410",
    "마포구": "440",
    "양천구": "470",
    "강서구": "500",
    "구로구": "530",
    "금천구": "545",
    "영등포구": "560",
    "동작구": "590",
    "관악구": "620",
    "서초구": "650",
    "강남구": "680",
    "송파구": "710",
    "강동구": "740",
}


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def blank_to_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def load_items(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError(f"{path} has invalid items payload")
    return items


def resolve_district_code(item: dict[str, Any]) -> str:
    district_code = str(item.get("lDongSignguCd") or "")
    if district_code:
        return district_code

    # The source has a few blank lDongSignguCd values; infer only from explicit gu text.
    addr1 = str(item.get("addr1") or "")
    for district_name, inferred_code in DISTRICT_NAME_TO_CODE.items():
        if district_name in addr1:
            return inferred_code
    return district_code


def build_location_values(item: dict[str, Any], fallback_content_type_id: str, category: str) -> dict[str, Any]:
    district_code = resolve_district_code(item)
    sigungu_name = DISTRICT_CODES.get(district_code, "UNKNOWN")
    return {
        "content_id": str(item.get("contentid") or ""),
        "content_type_id": str(item.get("contenttypeid") or fallback_content_type_id),
        "category": category,
        "title": str(item.get("title") or ""),
        "addr1": blank_to_none(item.get("addr1")),
        "map_x": parse_float(item.get("mapx")),
        "map_y": parse_float(item.get("mapy")),
        "first_image": blank_to_none(item.get("firstimage")),
        "l_dong_signgu_cd": district_code,
        "sigungu_name": sigungu_name,
        "lcls_systm_1": blank_to_none(item.get("lclsSystm1")),
        "lcls_systm_2": blank_to_none(item.get("lclsSystm2")),
        "lcls_systm_3": blank_to_none(item.get("lclsSystm3")),
    }


def seed_locations() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()

    settings = get_settings()
    data_dir = Path(settings.seoul_data_dir)
    expected_total = sum(entry[3] for entry in CATEGORY_FILES)

    total_processed = 0
    total_skipped = 0
    total_mapping_failures = 0

    with SessionLocal() as session:
        for filename, content_type_id, category, expected_count in CATEGORY_FILES:
            path = data_dir / filename
            items = load_items(path)
            processed = 0
            skipped = 0
            mapping_failures = 0

            if len(items) != expected_count:
                logger.warning(
                    "%s expected %s rows but found %s rows",
                    filename,
                    expected_count,
                    len(items),
                )

            for item in items:
                values = build_location_values(item, content_type_id, category)
                if not values["content_id"]:
                    logger.warning("%s has a row without contentid; skipping", filename)
                    skipped += 1
                    continue

                if values["sigungu_name"] == "UNKNOWN":
                    mapping_failures += 1
                    logger.warning(
                        "Unknown lDongSignguCd=%s for content_id=%s",
                        values["l_dong_signgu_cd"],
                        values["content_id"],
                    )

                existing_id = session.scalar(
                    select(Location.id).where(Location.content_id == values["content_id"])
                )
                if existing_id is None:
                    session.add(Location(**values))
                    processed += 1
                else:
                    session.execute(
                        update(Location)
                        .where(Location.id == existing_id)
                        .values(**values)
                    )
                    skipped += 1

            session.commit()
            total_processed += processed
            total_skipped += skipped
            total_mapping_failures += mapping_failures

            print(
                f"{filename}: processed={processed}, skipped={skipped}, "
                f"mapping_failures={mapping_failures}, source_rows={len(items)}"
            )

        final_total = session.scalar(select(func.count()).select_from(Location))
        print(f"locations_total={final_total}")
        print(
            f"summary: processed={total_processed}, skipped={total_skipped}, "
            f"mapping_failures={total_mapping_failures}, expected_source_rows={expected_total}"
        )


if __name__ == "__main__":
    seed_locations()
