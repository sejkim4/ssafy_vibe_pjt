from fastapi import FastAPI


app = FastAPI(title="Seoul Vibe Backend")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
