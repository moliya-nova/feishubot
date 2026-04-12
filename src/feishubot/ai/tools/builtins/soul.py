from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from feishubot.ai.prompts import load_soul_prompt, save_soul_prompt
from feishubot.ai.tools.base import Tool


class SoulMemoryArguments(BaseModel):
    user_name: str | None = Field(default=None, max_length=120)
    assistant_name: str | None = Field(default=None, max_length=120)
    habits: str | None = Field(default=None, max_length=120)
    hobbies: str | None = Field(default=None, max_length=120)
    preferences: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=120)


class SoulMemoryTool(Tool):
    name = "soul_memory"
    description = (
        "Update the startup persona file SOUL.md with stable user identity and preferences."
    )
    args_model = SoulMemoryArguments
    _MAX_RECENT_UPDATES = 3
    _MAX_SNIPPET_LENGTH = 120

    @staticmethod
    def _normalize_text(value: str, *, max_length: int) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max_length - 1].rstrip() + "…"

    @classmethod
    def _summarize_note(cls, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized:
            return ""

        parts = re.split(r"[。！？!?;；\n]", normalized, maxsplit=1)
        summary = parts[0].strip() if parts else normalized
        if not summary:
            summary = normalized
        return cls._normalize_text(summary, max_length=80)

    @staticmethod
    def _extract_field(content: str, prefix: str) -> str:
        pattern = re.compile(rf"^{re.escape(prefix)}\s*(.*)$", flags=re.MULTILINE)
        match = pattern.search(content)
        if match is None:
            return "未配置"
        value = match.group(1).strip()
        return value or "未配置"

    @classmethod
    def _extract_recent_updates(cls, content: str) -> list[str]:
        match = re.search(
            r"^## 最近更新\n(?P<body>(?:- .*(?:\n|$))*)",
            content,
            flags=re.MULTILINE,
        )
        if match is None:
            return []

        updates: list[str] = []
        for line in match.group("body").splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            entry = stripped[2:].strip()
            if entry:
                updates.append(entry)
        return updates[: cls._MAX_RECENT_UPDATES]

    @classmethod
    def _format_soul_prompt(
        cls,
        *,
        user_name: str,
        assistant_name: str,
        habits: str,
        hobbies: str,
        preferences: str,
        recent_updates: list[str],
    ) -> str:
        sections = [
            "# FeishuBot 核心人格文件",
            "",
            "该文件会在服务启动时自动加载，并作为所有模型调用的基础 system prompt。",
            "",
            "## 固定身份信息",
            "",
            f"- 用户姓名：{user_name}",
            f"- 用户为大模型起的姓名：{assistant_name}",
            "- 当前模型称呼：FeishuBot",
            "",
            "## 用户画像",
            "",
            f"- 用户习惯：{habits}",
            f"- 用户爱好：{hobbies}",
            f"- 用户偏好：{preferences}",
            "",
            "## 行为要求",
            "",
            "- 先记住用户的姓名、称呼、习惯和爱好，再回答问题。",
            "- 后续回答尽量保持和用户习惯一致的语气、长度和结构。",
            "- 如果关键信息缺失，先沿用最近一次已知信息；没有已知信息时再主动询问。",
            "- 这个文件属于核心人格层，不应按需加载，而应随进程启动自动加载。",
            "- 当模型通过可用工具或人工维护流程获得新的稳定信息时，",
            "  应调用 `soul_memory` 工具更新本文件。",
        ]

        if recent_updates:
            sections.extend(
                [
                    "",
                    "## 最近更新",
                    "",
                ]
            )
            sections.extend(f"- {item}" for item in recent_updates[: cls._MAX_RECENT_UPDATES])

        return "\n".join(sections).rstrip() + "\n"

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        current = load_soul_prompt()
        user_name = self._extract_field(current, "- 用户姓名：")
        assistant_name = self._extract_field(current, "- 用户为大模型起的姓名：")
        habits = self._extract_field(current, "- 用户习惯：")
        hobbies = self._extract_field(current, "- 用户爱好：")
        preferences = self._extract_field(current, "- 用户偏好：")
        recent_updates = self._extract_recent_updates(current)

        changes: list[str] = []

        raw_user_name = str(arguments.get("user_name") or "").strip()
        if raw_user_name:
            user_name = self._normalize_text(raw_user_name, max_length=self._MAX_SNIPPET_LENGTH)
            changes.append("user_name")

        raw_assistant_name = str(arguments.get("assistant_name") or "").strip()
        if raw_assistant_name:
            assistant_name = self._normalize_text(
                raw_assistant_name, max_length=self._MAX_SNIPPET_LENGTH
            )
            changes.append("assistant_name")

        raw_habits = str(arguments.get("habits") or "").strip()
        if raw_habits:
            habits = self._normalize_text(raw_habits, max_length=self._MAX_SNIPPET_LENGTH)
            changes.append("habits")

        raw_hobbies = str(arguments.get("hobbies") or "").strip()
        if raw_hobbies:
            hobbies = self._normalize_text(raw_hobbies, max_length=self._MAX_SNIPPET_LENGTH)
            changes.append("hobbies")

        raw_preferences = str(arguments.get("preferences") or "").strip()
        if raw_preferences:
            preferences = self._normalize_text(raw_preferences, max_length=self._MAX_SNIPPET_LENGTH)
            changes.append("preferences")

        notes = str(arguments.get("notes") or "").strip()
        if notes:
            summary = self._summarize_note(notes)
            recent_updates = [summary, *recent_updates]
            recent_updates = recent_updates[: self._MAX_RECENT_UPDATES]
            changes.append("notes")

        updated = self._format_soul_prompt(
            user_name=user_name,
            assistant_name=assistant_name,
            habits=habits,
            hobbies=hobbies,
            preferences=preferences,
            recent_updates=recent_updates,
        )

        if updated == current:
            return {"status": "unchanged", "updated_fields": [], "path": "SOUL.md"}

        save_soul_prompt(updated)
        return {
            "status": "updated",
            "updated_fields": changes,
            "path": "SOUL.md",
        }
