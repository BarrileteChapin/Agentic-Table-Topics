"""Sequential Toastmasters roles. Timer and Ah-Counter do not call a model."""

from __future__ import annotations

import json
import re

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event, EventActions
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from typing_extensions import AsyncGenerator, override

from app.foundry import api_base, litellm_model
from app.reports import ah_counter_report, dumps, timer_report

APP_NAME = "toastmasters"


def language_model(max_tokens: int) -> LiteLlm:
    return LiteLlm(
        model=litellm_model(),
        api_base=api_base(),
        api_key="foundry-local",
        temperature=0.2,
        max_tokens=max_tokens,
    )


def _event(author: str, payload: dict) -> Event:
    text = dumps(payload)
    delta = {f"{author}_report": text}
    if payload.get("note"):
        delta[f"{author}_note"] = payload["note"]
    return Event(
        author=author,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        actions=EventActions(state_delta=delta),
    )


class TimerAgent(BaseAgent):
    @override
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        report = timer_report(
            float(state.get("elapsed_seconds") or 0),
            float(state.get("target_seconds") or 0),
        )
        yield _event("Timer", report)


class AhCounterAgent(BaseAgent):
    @override
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        report = ah_counter_report(str(ctx.session.state.get("transcript") or ""))
        yield _event("AhCounter", report)


_PROMPT_KEYS = (
    "speech",
    "topic",
    "Timer_note",
    "Grammarian_report",
    "AhCounter_note",
    "Reviewer_report",
    "pace_note",
)


def _fill(template: str, state: dict) -> str:
    text = template
    for key in _PROMPT_KEYS:
        text = text.replace("{" + key + "}", str(state.get(key) or ""))
    return text


async def _complete(prompt: str, max_tokens: int) -> str:
    model = language_model(max_tokens)
    request = LlmRequest(
        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),
    )
    final = ""
    partials: list[str] = []
    async for response in model.generate_content_async(request, stream=False):
        if response.error_message:
            raise RuntimeError(response.error_message)
        content = response.content
        chunks = []
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "thought", False):
                continue
            if getattr(part, "text", None):
                chunks.append(part.text)
        text = "".join(chunks).strip()
        if not text:
            continue
        if response.partial:
            partials.append(text)
        else:
            final = text
    return final or "".join(partials).strip()


def _note_field(note: str, label: str) -> str:
    from app.reports import first_sentence

    match = re.search(
        rf"{label}:\s*(.+?)(?=\s+(?:Worked|Change|Topic|Clarity|Organization):|$)",
        note or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return first_sentence(match.group(1) if match else "")


def _usable_sheet(text: str) -> bool:
    raw = lines_to_sheet(text)
    comments = " ".join(
        str(raw.get(key) or "")
        for key in ("clarity_comment", "content_comment", "excelled_at", "work_on")
    ).strip()
    if not comments or "**" in comments:
        return False
    return not comments.lower().startswith("timer")


def _sheet_from_notes(state: dict) -> str:
    worked = _note_field(str(state.get("Grammarian_report") or ""), "Worked")
    change = _note_field(str(state.get("Grammarian_report") or ""), "Change")
    topic = _note_field(str(state.get("Reviewer_report") or ""), "Topic")
    clarity = _note_field(str(state.get("Reviewer_report") or ""), "Clarity")
    organization = _note_field(str(state.get("Reviewer_report") or ""), "Organization")
    fillers = str(state.get("AhCounter_note") or "No tracked fillers.")
    lines = [
        f"Clarity: {clarity or worked}",
        f"Vocal variety: {fillers} Tone and volume were not captured.",
        f"Audience awareness: {topic}",
        f"Comfort level: {fillers} Inferred from fillers and pace, not from appearance.",
        f"Content: {topic}",
        f"Excelled at: {worked or clarity}",
        f"Work on: {change or organization}",
        f"Challenge: {organization or change}",
    ]
    return "\n".join(lines)


class SpeechAgent(BaseAgent):
    """One model call. The prompt is built from session state, not from earlier seats."""

    max_tokens: int
    instruction: str
    organized: bool = False

    @override
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        prompt = _fill(self.instruction, ctx.session.state)
        text = await _complete(prompt, self.max_tokens)
        if self.name == "Evaluator" and not _usable_sheet(text):
            text = _sheet_from_notes(ctx.session.state)
        stored = organize_seat(self.name, text)["note"] if self.organized else text
        yield Event(
            author=self.name,
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            actions=EventActions(state_delta={f"{self.name}_report": stored}),
        )


def build_club() -> SequentialAgent:
    grammarian = SpeechAgent(
        name="Grammarian",
        description="Notes clear strengths and problems in the wording.",
        max_tokens=140,
        organized=True,
        instruction=(
            "You are the grammarian. Judge only the speech below.\n"
            "Speech:\n{speech}\n\n"
            "Reply with exactly two lines and no other words:\n"
            "Worked: one sentence on wording that worked\n"
            "Change: one sentence on wording to change\n"
            "No markdown."
        ),
    )
    reviewer = SpeechAgent(
        name="Reviewer",
        description="Judges topic fit, clarity, and organization.",
        max_tokens=130,
        organized=True,
        instruction=(
            "You are the reviewer. Judge only the topic and the speech below.\n"
            "Topic: {topic}\n"
            "Speech:\n{speech}\n\n"
            "Reply with exactly three lines and no other words:\n"
            "Topic: one sentence on whether the speech answered the topic\n"
            "Clarity: one sentence\n"
            "Organization: one sentence\n"
            "No markdown. Do not mention appearance, gesture, or volume."
        ),
    )
    evaluator = SpeechAgent(
        name="Evaluator",
        description="Fills the evaluation sheet from the other roles.",
        max_tokens=420,
        instruction=(
            "You fill a Toastmasters evaluation sheet from these notes only.\n"
            "Timer: {Timer_note}\n"
            "Grammarian: {Grammarian_report}\n"
            "Ah-Counter: {AhCounter_note}\n"
            "Reviewer: {Reviewer_report}\n"
            "Pace: {pace_note}\n\n"
            "Use the notes above. Write exactly eight lines.\n"
            "After each label write a score from 1 to 5, then a colon, then your own remark.\n"
            "Never write the words 'one sentence' or 'comment'.\n"
            "Clarity: 3: remark from the notes\n"
            "Vocal variety: 3: remark from the pace and fillers. Tone and volume were not captured.\n"
            "Audience awareness: 3: remark from the notes\n"
            "Comfort level: 3: remark from the fillers and pace. Inferred from fillers and pace, not appearance.\n"
            "Content: 3: remark on whether the speech answered the topic\n"
            "Excelled at: the strongest point in the notes\n"
            "Work on: the clearest change from the notes\n"
            "Challenge: one next step from the notes"
        ),
    )
    return SequentialAgent(
        name="Club",
        description="Timer, grammarian, ah-counter, reviewer, then the evaluation sheet.",
        sub_agents=[
            TimerAgent(name="Timer", description="Compares the recording length to the target."),
            grammarian,
            AhCounterAgent(name="AhCounter", description="Tallies filler words."),
            reviewer,
            evaluator,
        ],
    )


_SHEET_KEYS = (
    "clarity_score",
    "clarity_comment",
    "vocal_variety_score",
    "vocal_variety_comment",
    "audience_awareness_score",
    "audience_awareness_comment",
    "comfort_level_score",
    "comfort_level_comment",
    "content_score",
    "content_comment",
    "excelled_at",
    "work_on",
    "challenge",
)


def _repair_json(blob: str) -> str:
    blob = re.sub(r",\s*([}\]])", r"\1", blob)
    blob = re.sub(
        r'((?:-?\d+(?:\.\d+)?)|true|false|null|"(?:\\.|[^"\\])*")\s*\n(\s*")',
        r"\1,\n\2",
        blob,
    )
    blob += "}" * max(blob.count("{") - blob.count("}"), 0)
    blob += "]" * max(blob.count("[") - blob.count("]"), 0)
    return blob


def parse_json_text(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "")
    starts = [index for index in (cleaned.find("{"), cleaned.find("[")) if index >= 0]
    if not starts:
        raise ValueError("Agent did not return JSON.")
    start = min(starts)
    opener = cleaned[start]
    closer = "}" if opener == "{" else "]"
    end = cleaned.rfind(closer)
    blob = cleaned[start : end + 1] if end > start else cleaned[start:]
    value = json.loads(_repair_json(blob))
    if isinstance(value, list):
        if len(value) == 2 and all(isinstance(item, list) for item in value):
            return {"strengths": [str(item) for item in value[0]], "issues": [str(item) for item in value[1]]}
        return {"items": value}
    if not isinstance(value, dict):
        raise ValueError("Agent did not return a JSON object.")
    return value


def salvage_sheet(text: str) -> dict:
    raw: dict = {}
    for key in _SHEET_KEYS:
        match = re.search(
            rf'"{key}"\s*:\s*("(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|true|false|null)',
            text,
            flags=re.DOTALL,
        )
        if not match:
            continue
        try:
            raw[key] = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    return raw


_LINE_FIELDS = (
    ("clarity", "clarity"),
    ("vocal", "vocal_variety"),
    ("audience", "audience_awareness"),
    ("comfort", "comfort_level"),
    ("content", "content"),
    ("excelled", "excelled_at"),
    ("work on", "work_on"),
    ("challenge", "challenge"),
)
_CLOSING_KEYS = {"excelled_at", "work_on", "challenge"}
_PLACEHOLDER = re.compile(
    r"^(one sentence|a sentence|your (own )?remark|remark from the notes|comment)\b",
    re.IGNORECASE,
)


def _drop_placeholder(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip().strip("\"'")
    if not cleaned or _PLACEHOLDER.match(cleaned):
        return ""
    return cleaned


def lines_to_sheet(text: str) -> dict:
    raw: dict = {}
    for line in (text or "").splitlines():
        cleaned = re.sub(r"^[\s*•\-–—]+", "", line).strip()
        if ":" not in cleaned:
            continue
        label, rest = cleaned.split(":", 1)
        key = next((field for prefix, field in _LINE_FIELDS if label.strip().lower().startswith(prefix)), None)
        if key is None:
            continue
        rest = re.sub(r"^[\s*•\-–—]+", "", rest).strip()
        if key in _CLOSING_KEYS:
            comment = _drop_placeholder(rest)
            if comment:
                raw[key] = comment
            continue
        match = re.match(r"([1-5])\s*[:\-–—.]\s*(.*)", rest)
        if match:
            raw[f"{key}_score"] = int(match.group(1))
            comment = _drop_placeholder(match.group(2))
            if comment:
                raw[f"{key}_comment"] = comment
        else:
            comment = _drop_placeholder(rest)
            if comment:
                raw[f"{key}_comment"] = comment
    return raw


_TYPE_TO_KEY = {
    "clarity": "clarity",
    "vocalvariety": "vocal_variety",
    "audienceawareness": "audience_awareness",
    "audience": "audience_awareness",
    "comfortlevel": "comfort_level",
    "comfort": "comfort_level",
    "content": "content",
    "excelledat": "excelled_at",
    "excelled": "excelled_at",
    "workon": "work_on",
    "challenge": "challenge",
}


def _sheet_key(label: str) -> str | None:
    token = re.sub(r"[^a-z]", "", label.lower())
    if token in _TYPE_TO_KEY:
        return _TYPE_TO_KEY[token]
    return next((field for name, field in _TYPE_TO_KEY.items() if token.startswith(name)), None)


def _apply_item(raw: dict, item: dict) -> None:
    key = _sheet_key(str(item.get("type") or item.get("name") or item.get("category") or ""))
    if not key:
        return
    if key in _CLOSING_KEYS:
        comment = str(item.get("comment") or item.get("text") or "").strip()
        if comment:
            raw[key] = comment
        return
    if item.get("score") is not None:
        raw[f"{key}_score"] = item.get("score")
    comment = str(item.get("comment") or item.get("text") or "").strip()
    if comment:
        raw[f"{key}_comment"] = comment


def objects_to_sheet(value) -> dict:
    raw: dict = {}
    items = value if isinstance(value, list) else []
    if isinstance(value, dict):
        for key in _CLOSING_KEYS:
            if value.get(key):
                raw[key] = value[key]
        nested = value.get("items") or value.get("categories") or value.get("scores")
        if isinstance(nested, list):
            items = nested
    for item in items:
        if isinstance(item, dict):
            _apply_item(raw, item)
    return raw


def _has_sheet(raw: dict) -> bool:
    return any(raw.get(key) for key in _SHEET_KEYS)


def sheet_from_evaluator(text: str) -> dict:
    from app.reports import evaluation_sheet

    raw: dict = {}
    try:
        parsed = parse_json_text(text)
    except (ValueError, json.JSONDecodeError):
        raw = salvage_sheet(text)
    else:
        if isinstance(parsed, dict) and _has_sheet(parsed):
            raw = parsed
        else:
            raw = objects_to_sheet(parsed)
    if not _has_sheet(raw):
        raw = lines_to_sheet(text)
    if not _has_sheet(raw):
        prose = readable_report(text)
        if prose[:1] in "{[":
            prose = "The notes are beside this sheet."
        raw = {
            "clarity_comment": prose,
            "content_comment": prose,
            "excelled_at": prose,
            "work_on": "Use the grammarian and reviewer notes beside this sheet.",
        }
    return evaluation_sheet(raw)


def readable_report(text: str) -> str:
    cleaned = re.sub(r"```(?:json)?", "", text or "", flags=re.IGNORECASE).replace("```", "").strip()
    try:
        data = parse_json_text(cleaned)
    except (ValueError, json.JSONDecodeError):
        if cleaned[:1] in "{[":
            return "Wording notes could not be read as sentences."
        return cleaned
    items = data.get("items") if isinstance(data.get("items"), list) else []
    sentences = [
        str(item.get("comment") or item.get("text") or "").strip()
        for item in items
        if isinstance(item, dict)
    ]
    sentences = [sentence for sentence in sentences if sentence and sentence[:1] not in "{["]
    if sentences:
        return " ".join(sentences)
    if data.get("note"):
        return str(data["note"]).strip()
    strengths = data.get("strengths") if isinstance(data.get("strengths"), list) else []
    issues = data.get("issues") if isinstance(data.get("issues"), list) else []
    if strengths or issues:
        good = f"Worked: {'; '.join(str(item) for item in strengths)}." if strengths else ""
        watch = f"Change: {'; '.join(str(item) for item in issues)}." if issues else ""
        return " ".join(part for part in (good, watch) if part) or "No wording notes."
    summary = str(data.get("summary") or "").strip()
    if summary:
        return summary
    if cleaned[:1] in "{[":
        return "Wording notes could not be read as sentences."
    return cleaned


_SEAT_LABELS = {
    "Grammarian": ("Worked", "Change"),
    "Reviewer": ("Topic", "Clarity", "Organization"),
}


def organize_seat(author: str, text: str) -> dict:
    from app.reports import first_sentence

    labels = _SEAT_LABELS.get(author)
    if not labels:
        return {"note": readable_report(text)}

    cleaned = re.sub(r"```(?:json)?", "", text or "", flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s+(Worked|Change|Topic|Clarity|Organization)\s*:",
        r"\n\1:",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s*[-*]\s*\*\*([A-Za-z][A-Za-z ]{0,24})\*\*\s*:",
        r"\n\1:",
        cleaned,
    )
    cleaned = re.sub(r"\*\*([A-Za-z][A-Za-z ]{0,24})\*\*\s*:", r"\n\1:", cleaned)
    parts = re.split(
        r"(?:^|\n)\s*(Worked|Change|Topic|Clarity|Organization)\s*:\s*",
        cleaned,
        flags=re.IGNORECASE,
    )
    found: dict[str, str] = {}
    preamble = parts[0]
    for index in range(1, len(parts) - 1, 2):
        label = parts[index].strip().title()
        if label in labels and label not in found:
            sentence = first_sentence(parts[index + 1])
            if sentence:
                found[label] = sentence
    if labels[0] not in found:
        opening = first_sentence(preamble)
        if opening:
            found[labels[0]] = opening
    used = {line.lower() for line in found.values()}
    pool = [first_sentence(piece) for piece in re.findall(r"[^.!?]+[.!?]", preamble or "")]
    for label in labels:
        if label in found:
            continue
        for sentence in pool:
            if sentence and sentence.lower() not in used:
                found[label] = sentence
                used.add(sentence.lower())
                break
    lines = [{"label": label, "text": found[label]} for label in labels if found.get(label)]
    if not lines:
        fallback = first_sentence(readable_report(text))
        lines = [{"label": labels[0], "text": fallback or "No note."}]
    return {
        "lines": lines,
        "note": " ".join(f"{line['label']}: {line['text']}" for line in lines),
    }
