"""Local speech-to-text with Distil-Whisper Small English."""

from __future__ import annotations

import os
from functools import lru_cache

LONG_PAUSE_SECONDS = 1.0
MODEL_NAME = "Systran/faster-distil-whisper-small.en"
LOCAL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "distil-small.en"))
LOCAL_WEIGHT_BYTES = 332308257


def pace_from_transcript(transcript: str, elapsed_seconds: float) -> dict:
    words = len((transcript or "").split())
    minutes = elapsed_seconds / 60 if elapsed_seconds else 0
    return {
        "words": words,
        "wpm": round(words / minutes) if minutes else 0,
        "long_pauses": None,
        "source": "typed text; pauses were not heard",
    }


def _model_source() -> str:
    weight = os.path.join(LOCAL_DIR, "model.bin")
    if os.path.isfile(weight) and os.path.getsize(weight) >= LOCAL_WEIGHT_BYTES:
        return LOCAL_DIR
    return MODEL_NAME


def _patch_audio_open() -> None:
    import av

    if getattr(av.open, "_club_compat", False):
        return
    original = av.open

    def open_compat(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return original(*args, **kwargs)

    open_compat._club_compat = True
    av.open = open_compat


@lru_cache(maxsize=1)
def _model():
    _patch_audio_open()
    from faster_whisper import WhisperModel

    return WhisperModel(_model_source(), device="cpu", compute_type="int8")


def transcribe(path: str) -> dict:
    segments, info = _model().transcribe(path, language="en", vad_filter=True)
    pieces: list[dict] = []
    texts: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        pieces.append({"start": float(segment.start), "end": float(segment.end), "text": text})
        if text:
            texts.append(text)

    transcript = " ".join(texts).strip()
    duration = float(getattr(info, "duration", 0) or 0)
    if pieces:
        duration = max(duration, pieces[-1]["end"])

    words = len(transcript.split()) if transcript else 0
    minutes = duration / 60 if duration else 0
    long_pauses = 0
    previous_end = 0.0
    for piece in pieces:
        if previous_end and piece["start"] - previous_end >= LONG_PAUSE_SECONDS:
            long_pauses += 1
        previous_end = piece["end"]

    return {
        "transcript": transcript,
        "elapsed_seconds": round(duration, 1),
        "pace": {
            "words": words,
            "wpm": round(words / minutes) if minutes else 0,
            "long_pauses": long_pauses,
        },
    }
