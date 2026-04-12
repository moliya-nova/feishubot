"""Prompt templates and prompt-loading helpers."""

from __future__ import annotations

import os
import tempfile
import threading
from importlib import resources
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent
_SOUL_TEMPLATE_PATH = _PROMPTS_DIR / "system" / "SOUL.md"
_SOUL_LOCK = threading.Lock()


def _default_soul_prompt() -> str:
    template = resources.files("feishubot.ai.prompts").joinpath("system/SOUL.md")
    try:
        return template.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return _SOUL_TEMPLATE_PATH.read_text(encoding="utf-8").strip()


def get_soul_prompt_path() -> Path:
    configured_path = os.environ.get("SOUL_PROMPT_PATH", "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return Path.home() / ".feishubot" / "SOUL.md"


def _ensure_soul_prompt_exists() -> str:
    soul_path = get_soul_prompt_path()
    if soul_path.exists():
        return soul_path.read_text(encoding="utf-8").strip()

    soul_path.parent.mkdir(parents=True, exist_ok=True)
    default_prompt = _default_soul_prompt()
    save_soul_prompt(default_prompt)
    return default_prompt


def load_soul_prompt() -> str:
    """Load the startup persona prompt that should always be present."""
    return _ensure_soul_prompt_exists()


def save_soul_prompt(content: str) -> None:
    """Persist the startup persona prompt so the model can update it over time."""
    normalized = content.strip()
    soul_path = get_soul_prompt_path()
    soul_path.parent.mkdir(parents=True, exist_ok=True)

    with _SOUL_LOCK:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=soul_path.parent,
            prefix=".SOUL.",
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(normalized + "\n")
            temp_file_path = Path(temp_file.name)

        os.replace(temp_file_path, soul_path)

    global SOUL_PROMPT, CORE_PERSONA_PROMPT
    SOUL_PROMPT = normalized
    CORE_PERSONA_PROMPT = normalized


SOUL_PROMPT = load_soul_prompt()


def build_system_prompt(*parts: str | None, include_core: bool = True) -> str:
    """Join prompt fragments into a single system prompt."""
    fragments: list[str] = []
    if include_core:
        soul_prompt = load_soul_prompt()
        if soul_prompt:
            fragments.append(soul_prompt)

    for part in parts:
        if part is None:
            continue
        cleaned = part.strip()
        if cleaned:
            fragments.append(cleaned)

    return "\n\n".join(fragments)


CORE_PERSONA_PROMPT = SOUL_PROMPT


def load_core_persona_prompt() -> str:
    """Backward-compatible alias for loading the SOUL prompt."""
    return load_soul_prompt()


def save_core_persona_prompt(content: str) -> None:
    """Backward-compatible alias for updating the SOUL prompt."""
    save_soul_prompt(content)


__all__ = [
    "CORE_PERSONA_PROMPT",
    "SOUL_PROMPT",
    "build_system_prompt",
    "load_core_persona_prompt",
    "load_soul_prompt",
    "save_core_persona_prompt",
    "save_soul_prompt",
]
