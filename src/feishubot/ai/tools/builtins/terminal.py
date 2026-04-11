from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from feishubot.ai.tools.base import Tool


class TerminalArguments(BaseModel):
    mode: str = Field(default="sync")
    command: str | None = Field(default=None, min_length=1, max_length=4000)
    cwd: str | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)
    allow_dangerous: bool = False
    task_id: str | None = None


class TerminalCommandTool(Tool):
    name = "terminal"
    description = (
        "Execute a shell command and return stdout, stderr, exit code, and timeout status."
    )
    args_model = TerminalArguments

    _DANGEROUS_COMMAND_PATTERNS: tuple[str, ...] = (
        r"(^|\s)rm\s+-rf\s+/",
        r"(^|\s)(reboot|shutdown|halt|poweroff)(\s|$)",
        r"(^|\s)mkfs(\.|\s|$)",
        r"(^|\s)dd\s+if=",
        r"\bcurl\b[^\n|;]*\|[^\n]*\b(sh|bash|zsh)\b",
        r"\bwget\b[^\n|;]*\|[^\n]*\b(sh|bash|zsh)\b",
        r":\(\)\s*\{\s*:\|:\s*&\s*\};:",
    )
    _user_blocked_commands: tuple[str, ...] = ()
    _tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

    @classmethod
    def configure_blocked_commands(cls, blocked_commands: list[str]) -> None:
        cls._user_blocked_commands = tuple(
            command.strip().lower() for command in blocked_commands if command.strip()
        )

    @classmethod
    def _validate_command(cls, command: str, *, allow_dangerous: bool) -> None:
        if not command:
            raise ValueError("terminal requires a 'command' argument")
        if len(command) > 4000:
            raise ValueError("command too long")

        lowered = command.lower()
        for blocked_command in cls._user_blocked_commands:
            if blocked_command in lowered:
                raise ValueError(f"command blocked by configured policy: {blocked_command}")

        if allow_dangerous:
            return

        for pattern in cls._DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, lowered):
                raise ValueError("command blocked by safety policy")

    @staticmethod
    async def _run_command(
        *,
        command: str,
        cwd_path: Path | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd_path) if cwd_path is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        return {
            "command": command,
            "cwd": str(cwd_path) if cwd_path is not None else None,
            "timeout_seconds": timeout_seconds,
            "timed_out": timed_out,
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode = str(arguments.get("mode", "sync")).strip().lower()
        if mode not in {"sync", "start_async", "get_async_result", "cancel_async"}:
            raise ValueError(
                "terminal mode must be one of: sync, start_async, get_async_result, cancel_async"
            )

        command = str(arguments.get("command") or "").strip()
        allow_dangerous = bool(arguments.get("allow_dangerous", False))
        timeout_seconds = float(arguments.get("timeout_seconds", 60.0))
        task_id = str(arguments.get("task_id") or "").strip()

        cwd_path = None
        if mode in {"sync", "start_async"}:
            self._validate_command(command, allow_dangerous=allow_dangerous)

            cwd_value = arguments.get("cwd")
            if cwd_value:
                cwd_path = Path(str(cwd_value)).expanduser().resolve()
                if not cwd_path.exists():
                    raise ValueError(f"cwd does not exist: {cwd_path}")

        if mode == "sync":
            return await self._run_command(
                command=command,
                cwd_path=cwd_path,
                timeout_seconds=timeout_seconds,
            )

        if mode == "start_async":
            task_id = str(uuid.uuid4())
            task = asyncio.create_task(
                self._run_command(
                    command=command,
                    cwd_path=cwd_path,
                    timeout_seconds=timeout_seconds,
                )
            )
            self._tasks[task_id] = task
            return {
                "task_id": task_id,
                "status": "running",
                "command": command,
                "cwd": str(cwd_path) if cwd_path is not None else None,
                "timeout_seconds": timeout_seconds,
            }

        if not task_id:
            raise ValueError("terminal requires 'task_id' for get_async_result/cancel_async")

        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"async task not found: {task_id}")

        if mode == "cancel_async":
            if not task.done():
                task.cancel()
            self._tasks.pop(task_id, None)
            return {"task_id": task_id, "status": "cancelled"}

        if not task.done():
            return {"task_id": task_id, "status": "running"}

        self._tasks.pop(task_id, None)
        try:
            result = task.result()
        except Exception as exc:  # noqa: BLE001
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(exc),
            }

        result["task_id"] = task_id
        result["status"] = "completed"
        return result
