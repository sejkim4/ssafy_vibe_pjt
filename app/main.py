from fastapi import FastAPI
from app.routers import locations, matches, reviews, board

app = FastAPI(title="Seoul Vibe Backend")

app.include_router(locations.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(board.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

