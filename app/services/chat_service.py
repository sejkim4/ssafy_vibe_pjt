from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.location import Location
from app.models.match import Match, MatchGame
from app.schemas.chat import ChatMessage
from app.services import review_service


RECENT_REVIEW_LIMIT = 3
OPENAI_TIMEOUT_SECONDS = 20.0


class GameNotFoundError(Exception):
    pass


class MatchAlreadyFinishedError(Exception):
    pass


class ChatUpstreamError(Exception):
    pass


def generate_reply(
    db: Session,
    match_id: int,
    game_id: int,
    message: str,
    history: list[ChatMessage],
) -> str:
    game = db.query(MatchGame).filter(
        MatchGame.match_id == match_id,
        MatchGame.id == game_id,
    ).first()
    if not game:
        raise GameNotFoundError()

    match = db.query(Match).filter(Match.id == match_id).first()
    if match and match.status == "finished":
        raise MatchAlreadyFinishedError()

    location_a = game.location_a or db.get(Location, game.location_a_id)
    location_b = game.location_b or db.get(Location, game.location_b_id)
    if not location_a or not location_b:
        raise GameNotFoundError()

    reviews_a = _recent_review_contents(db, location_a.id)
    reviews_b = _recent_review_contents(db, location_b.id)
    system_prompt = build_system_prompt(location_a, location_b, reviews_a, reviews_b)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": item.role, "content": item.content} for item in history)
    messages.append({"role": "user", "content": message})

    return _create_openai_reply(messages)


def _recent_review_contents(db: Session, location_id: int) -> list[str]:
    reviews, _ = review_service.list_reviews(
        db=db,
        location_id=location_id,
        page=1,
        size=RECENT_REVIEW_LIMIT,
    )
    return [review.content for review in reviews]


def build_system_prompt(
    location_a: Location,
    location_b: Location,
    reviews_a: list[str],
    reviews_b: list[str],
) -> str:
    sections = [
        "당신은 서울 여행지 이상형 월드컵의 경기 중 A/B 비교를 돕는 챗봇입니다.",
        "반드시 한국어로 답변하세요.",
        "답변 범위는 현재 경기의 A 장소와 B 장소에 대해 아래에 제공된 DB 장소 정보와 사용자 리뷰 내용으로만 제한됩니다.",
        "제공되지 않은 정보(전화번호, 운영시간, 주차, 입장료, 메뉴, 예약, 혼잡도 등)는 추측하거나 지어내지 말고 '제공된 정보만으로는 알 수 없습니다'라고 말하세요.",
        "사용자 리뷰는 방문자 한 명의 주관적 의견이며 검증된 사실이 아닙니다. 리뷰를 근거로 말할 때는 '리뷰에서는 ...라고 언급했습니다'처럼 의견으로 표현하세요.",
        "다른 장소, 다른 경기, 전체 랭킹, 현재 경기 A/B 이외 장소의 리뷰는 언급하지 마세요.",
        "",
        _format_location_section("A", location_a),
    ]
    if reviews_a:
        sections.extend(["", _format_reviews_section("A", reviews_a)])
    sections.extend(["", _format_location_section("B", location_b)])
    if reviews_b:
        sections.extend(["", _format_reviews_section("B", reviews_b)])
    return "\n".join(sections)


def _format_location_section(label: str, location: Location) -> str:
    fields = [
        f"{label} 장소 정보",
        f"- title: {location.title}",
        f"- category_name: {location.category}",
        f"- addr1: {_display_value(location.addr1)}",
        f"- sigungu_name: {location.sigungu_name}",
    ]
    optional_fields = [
        ("lcls_systm_1", location.lcls_systm_1),
        ("lcls_systm_2", location.lcls_systm_2),
        ("lcls_systm_3", location.lcls_systm_3),
    ]
    for name, value in optional_fields:
        if value:
            fields.append(f"- {name}: {value}")
    return "\n".join(fields)


def _format_reviews_section(label: str, reviews: list[str]) -> str:
    lines = [f"{label} 사용자 리뷰"]
    lines.extend(f"- {content}" for content in reviews)
    return "\n".join(lines)


def _display_value(value: str | None) -> str:
    return value if value else "제공되지 않음"


def _create_openai_reply(messages: list[dict[str, str]]) -> str:
    settings = get_settings()
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
        response: Any = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            timeout=OPENAI_TIMEOUT_SECONDS,
        )
        reply = response.choices[0].message.content
        if not reply:
            raise ChatUpstreamError()
        return reply
    except ChatUpstreamError:
        raise
    except Exception as exc:
        raise ChatUpstreamError() from exc
