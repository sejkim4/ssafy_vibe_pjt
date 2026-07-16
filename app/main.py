from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import locations, matches, reviews, board, chat
from app.scripts.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Seoul Vibe Backend", lifespan=lifespan)

# TODO: 프로덕션 배포 전 allow_origins를 실제 프론트엔드 도메인으로 좁힐 것 (API명세서 §9)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(locations.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(board.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

