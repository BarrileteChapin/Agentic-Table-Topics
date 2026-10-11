"""Microsoft Foundry Local, reached through its OpenAI-compatible API."""

from __future__ import annotations

import contextvars
import json
import os
import re
import subprocess
from urllib.request import urlopen

DEFAULT_MODEL = "qwen2.5-1.5b-instruct-generic-gpu:4"
_choice: contextvars.ContextVar[str] = contextvars.ContextVar("foundry_model", default="")


def model_id() -> str:
    chosen = _choice.get().strip()
    if chosen:
        return chosen
    return os.environ.get("FOUNDRY_MODEL", DEFAULT_MODEL)


def select_model(model: str):
    return _choice.set(model)


def reset_model(token) -> None:
    _choice.reset(token)


def _label(model: str) -> str:
    name = re.sub(r"-generic.*$", "", model)
    name = name.replace("mistralai-", "")
    name = re.sub(r"-instruct", "", name, flags=re.IGNORECASE)
    return name or model


_cached_base = ""


def api_base() -> str:
    global _cached_base
    override = os.environ.get("FOUNDRY_API_BASE", "").strip()
    if override:
        return override.rstrip("/")
    if _cached_base:
        return _cached_base
    status = subprocess.run(
        ["foundry", "service", "status"],
        check=False,
        capture_output=True,
        text=True,
    )
    text = f"{status.stdout}\n{status.stderr}"
    match = re.search(r"http://127\.0\.0\.1:\d+", text)
    if not match:
        raise RuntimeError(
            "Foundry Local is not running. Start it with: foundry service start"
        )
    _cached_base = match.group(0) + "/v1"
    return _cached_base


def litellm_model() -> str:
    return f"openai/{model_id()}"


def available_models() -> list[dict]:
    with urlopen(f"{api_base()}/models", timeout=5) as response:
        payload = json.loads(response.read().decode())
    models = []
    seen: set[str] = set()
    for item in payload.get("data") or []:
        model = str(item.get("id") or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        models.append({"id": model, "label": _label(model)})
    models.sort(key=lambda item: (item["id"] != DEFAULT_MODEL, item["label"].lower()))
    return models


def resolve_model(requested: str) -> str:
    chosen = (requested or "").strip() or model_id()
    known = {item["id"] for item in available_models()}
    if known and chosen not in known:
        raise ValueError("That model is not available in Foundry.")
    return chosen
