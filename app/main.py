"""Web club: topic, recording, transcription, then the five seats."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncIterator

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents import APP_NAME, build_club, organize_seat, sheet_from_evaluator
from app.foundry import api_base, available_models, model_id, reset_model, resolve_model, select_model
from app.reports import speech_for_agents
from app.stt import pace_from_transcript, transcribe
from app.topics import random_topic

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MEDIA_DIR = os.path.join(os.path.dirname(__file__), "media")
SEAT_KEYS = {
    "Timer": "Timer_report",
    "Grammarian": "Grammarian_report",
    "AhCounter": "AhCounter_report",
    "Reviewer": "Reviewer_report",
    "Evaluator": "Evaluator_report",
}

app = FastAPI(title="Toastmasters speech club")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _text_from_event(event) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    chunks = []
    for part in parts:
        if getattr(part, "thought", False):
            continue
        text = getattr(part, "text", None)
        if text:
            chunks.append(text)
    return "".join(chunks).strip()


async def _run_club(state: dict) -> AsyncIterator[str]:
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id="speaker",
        state=state,
    )
    runner = Runner(
        agent=build_club(),
        app_name=APP_NAME,
        session_service=session_service,
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text="Evaluate this speech from the reports in state.")],
    )
    announced: set[str] = set()
    seen: set[str] = set()
    async for event in runner.run_async(
        user_id="speaker",
        session_id=session.id,
        new_message=message,
        run_config=RunConfig(streaming_mode=StreamingMode.NONE),
    ):
        author = getattr(event, "author", "")
        if author not in SEAT_KEYS or author in seen:
            continue
        if author not in announced:
            announced.add(author)
            yield _sse("working", {"name": author})
        if getattr(event, "partial", False):
            continue
        text = _text_from_event(event)
        if not text:
            continue
        seen.add(author)
        if author == "Evaluator":
            yield _sse("agent", {"name": author, "report": sheet_from_evaluator(text)})
        else:
            yield _sse("agent", {"name": author, "report": organize_seat(author, text)})

    missing = [name for name in SEAT_KEYS if name not in seen]
    if missing:
        raise RuntimeError(f"These roles did not report: {', '.join(missing)}.")


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/topic")
async def topic():
    return {"topic": random_topic()}


@app.get("/api/health")
async def health():
    return {"model": model_id(), "api_base": api_base()}


@app.get("/api/models")
async def models():
    listed = await asyncio.to_thread(available_models)
    selected = model_id()
    if listed and selected not in {item["id"] for item in listed}:
        selected = listed[0]["id"]
    return {"models": listed, "selected": selected}


class TextSpeech(BaseModel):
    topic: str
    transcript: str
    target_seconds: float = Field(gt=0)
    elapsed_seconds: float = Field(gt=0)
    model: str = ""


def _pace_note(pace: dict) -> str:
    pauses = pace.get("long_pauses")
    if pauses is None:
        pause_text = "Pauses were not heard."
    else:
        pause_text = f"Long pauses: {pauses}."
    return f"{pace.get('words', 0)} words, about {pace.get('wpm', 0)} per minute. {pause_text}"


def _club_payload(topic: str, target_seconds: float, elapsed_seconds: float, transcript: str, pace: dict) -> dict:
    return {
        "topic": topic.strip(),
        "target_seconds": float(target_seconds),
        "elapsed_seconds": float(elapsed_seconds),
        "transcript": transcript.strip(),
        "speech": speech_for_agents(transcript),
        "pace": json.dumps(pace),
        "pace_note": _pace_note(pace),
    }


async def _finish(payload: dict, heard: dict) -> AsyncIterator[str]:
    yield _sse(
        "transcript",
        {
            "transcript": heard["transcript"],
            "elapsed_seconds": heard["elapsed_seconds"],
            "pace": heard["pace"],
        },
    )
    yield _sse("status", {"phase": "evaluating"})
    async for chunk in _run_club(payload):
        yield chunk
    yield _sse("done", {})


@app.post("/api/text")
async def text_session(speech: TextSpeech):
    transcript = speech.transcript.strip()
    if not transcript:
        async def empty() -> AsyncIterator[str]:
            yield _sse("error", {"message": "Paste a speech before evaluating."})

        return StreamingResponse(empty(), media_type="text/event-stream")

    pace = pace_from_transcript(transcript, speech.elapsed_seconds)
    heard = {
        "transcript": transcript,
        "elapsed_seconds": speech.elapsed_seconds,
        "pace": pace,
    }
    payload = _club_payload(
        speech.topic, speech.target_seconds, speech.elapsed_seconds, transcript, pace
    )

    async def stream() -> AsyncIterator[str]:
        token = None
        try:
            token = select_model(resolve_model(speech.model))
            async for chunk in _finish(payload, heard):
                yield chunk
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})
        finally:
            if token is not None:
                reset_model(token)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/session")
async def session(
    audio: UploadFile = File(...),
    topic: str = Form(...),
    target_seconds: float = Form(...),
    model: str = Form(""),
):
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    audio_bytes = await audio.read()

    async def stream() -> AsyncIterator[str]:
        path = ""
        token = None
        try:
            token = select_model(resolve_model(model))
            yield _sse("status", {"phase": "transcribing"})
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                handle.write(audio_bytes)
                path = handle.name
            heard = await asyncio.to_thread(transcribe, path)
            payload = _club_payload(
                topic,
                target_seconds,
                heard["elapsed_seconds"],
                heard["transcript"],
                heard["pace"],
            )
            async for chunk in _finish(payload, heard):
                yield chunk
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})
        finally:
            if token is not None:
                reset_model(token)
            if path and os.path.exists(path):
                os.remove(path)

    return StreamingResponse(stream(), media_type="text/event-stream")
