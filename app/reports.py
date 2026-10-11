"""Deterministic timer and filler counts, plus the evaluation-sheet shape."""

from __future__ import annotations

import json
import re

FILLERS = (
    ("you know", re.compile(r"\byou know\b", re.IGNORECASE)),
    ("um", re.compile(r"\bum+\b", re.IGNORECASE)),
    ("uh", re.compile(r"\buh+\b", re.IGNORECASE)),
    ("ah", re.compile(r"\bah+\b", re.IGNORECASE)),
    ("er", re.compile(r"\ber+\b", re.IGNORECASE)),
    ("hmm", re.compile(r"\bhmm+\b", re.IGNORECASE)),
)

SCORE_LABELS = {
    5: "Exemplary",
    4: "Excels",
    3: "Accomplished",
    2: "Emerging",
    1: "Developing",
}

SCORED_CATEGORIES = (
    ("Clarity", "clarity"),
    ("Vocal Variety", "vocal_variety"),
    ("Audience Awareness", "audience_awareness"),
    ("Comfort Level", "comfort_level"),
    ("Content", "content"),
)


def timing_status(elapsed: float, target: float) -> str:
    if target <= 0:
        return "green"
    ratio = elapsed / target
    if ratio < 0.75:
        return "short"
    if ratio <= 1.0:
        return "green"
    if ratio <= 1.10:
        return "yellow"
    return "over"


def format_clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60}:{total % 60:02d}"


def timer_report(elapsed: float, target: float) -> dict:
    status = timing_status(elapsed, target)
    notes = {
        "short": "Short of the green window.",
        "green": "Inside the green window.",
        "yellow": "In the yellow window, just past the target.",
        "over": "Past the yellow window.",
    }
    return {
        "status": status,
        "elapsed_seconds": round(elapsed, 1),
        "target_seconds": round(target, 1),
        "note": (
            f"{format_clock(elapsed)} of a {format_clock(target)} target. "
            f"{notes[status]}"
        ),
    }


def ah_counter_report(transcript: str) -> dict:
    counts = {name: len(pattern.findall(transcript or "")) for name, pattern in FILLERS}
    counts = {name: count for name, count in counts.items() if count}
    total = sum(counts.values())
    if total == 0:
        note = "No tracked fillers."
    else:
        detail = ", ".join(f"{name} {count}" for name, count in counts.items())
        note = f"{total} filler{'s' if total != 1 else ''}: {detail}."
    return {"total": total, "counts": counts, "note": note}


def clamp_score(value) -> int | None:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return min(5, max(1, score))


def first_sentence(text: str, limit: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = re.sub(r"^[-–—*•\"']+\s*", "", cleaned)
    match = re.match(r"(.+?[.!?])(?:[\"']+\s|[\"']+$|\s|$)", cleaned)
    sentence = (match.group(1) if match else cleaned).strip()
    sentence = sentence.strip("\"'")
    if len(sentence) > limit:
        sentence = sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "."
    return sentence


def speech_for_agents(transcript: str) -> str:
    words = (transcript or "").split()
    if len(words) <= 160:
        return (transcript or "").strip()

    def passage(start: int, count: int) -> str:
        return " ".join(words[start : start + count])

    middle = max(0, len(words) // 2 - 20)
    return (
        f"Long speech, {len(words)} words. Read only these passages.\n"
        f"Opening: {passage(0, 70)}\n"
        f"Middle: {passage(middle, 40)}\n"
        f"Close: {passage(max(0, len(words) - 50), 50)}"
    )


def _comment(raw: dict, key: str, required_phrase: str) -> str:
    text = first_sentence(raw.get(f"{key}_comment") or "")
    if required_phrase.lower() not in text.lower():
        text = f"{text} {required_phrase}".strip()
    return text


def evaluation_sheet(raw: dict) -> dict:
    categories = []
    for name, key in SCORED_CATEGORIES:
        score = clamp_score(raw.get(f"{key}_score"))
        if key == "vocal_variety":
            comment = _comment(raw, key, "Tone and volume were not captured.")
        elif key == "comfort_level":
            comment = _comment(
                raw, key, "Inferred from fillers and pace, not from appearance."
            )
        else:
            comment = first_sentence(raw.get(f"{key}_comment") or "")
        categories.append(
            {
                "name": name,
                "score": score,
                "label": SCORE_LABELS.get(score) if score else None,
                "comment": comment,
            }
        )

    categories.insert(
        2,
        {
            "name": "Eye Contact",
            "score": None,
            "label": None,
            "comment": "Not observed — no camera.",
        },
    )
    categories.insert(
        3,
        {
            "name": "Gestures",
            "score": None,
            "label": None,
            "comment": "Not observed — no camera.",
        },
    )
    return {
        "categories": categories,
        "excelled_at": first_sentence(raw.get("excelled_at") or ""),
        "work_on": first_sentence(raw.get("work_on") or ""),
        "challenge": first_sentence(raw.get("challenge") or ""),
    }


def dumps(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False)
