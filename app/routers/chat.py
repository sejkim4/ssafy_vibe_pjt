from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import chat_service
from app.services.chat_service import (
    ChatUpstreamError,
    GameNotFoundError,
    MatchAlreadyFinishedError,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/chat", response_model=ChatResponse)
def post_chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    try:
        reply = chat_service.generate_reply(
            db=db,
            match_id=request.match_id,
            game_id=request.game_id,
            message=request.message,
            history=request.history,
        )
        return ChatResponse(reply=reply)
    except GameNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "GAME_NOT_FOUND",
                "message": "요청한 match_id/game_id 조합의 경기를 찾을 수 없습니다.",
            },
        )
    except MatchAlreadyFinishedError:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "MATCH_ALREADY_FINISHED",
                "message": "이미 종료된 매치입니다.",
            },
        )
    except ChatUpstreamError:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "CHAT_UPSTREAM_ERROR",
                "message": "챗봇 응답 생성에 실패했습니다. 잠시 후 다시 시도해주세요.",
            },
        )
