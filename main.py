from fastapi import FastAPI
from pydantic import BaseModel
from youtube_fetcher import fetch_transcript

app = FastAPI()


class TranscriptRequest(BaseModel):
    url: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/transcript")
def transcript(req: TranscriptRequest):
    try:
        text = fetch_transcript(req.url)
        return {"transcript": text}
    except Exception as exc:
        return {"error": str(exc), "transcript": ""}
