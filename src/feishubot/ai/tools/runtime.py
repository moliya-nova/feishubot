from __future__ import annotations

import asyncio
import json
import logging
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from feishubot.ai.core.errors import ToolNotFoundError
from feishubot.ai.tools.base import Tool
from feishubot.ai.tools.builtins import TerminalCommandTool, register_builtin_tools
from feishubot.ai.tools.registry import tool_registry
from feishubot.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ToolRoutingConfig:
    timeout_seconds: float | None = None


@dataclass(slots=True)
class TerminalPolicyConfig:
    blocked_commands: tuple[str, ...] = ()


@dataclass(slots=True)
class AsyncExecutionState:
    invocation_id: str
    name: str
    arguments: dict[str, Any]
    task: asyncio.Task[dict[str, Any]]


class ToolRuntime:
    _DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[4] / "tools.default.toml"

    def __init__(self, config_path: str | None = None) -> None:
        register_builtin_tools()
        self._enabled_tools: set[str] | None = None
        self._routing: dict[str, ToolRoutingConfig] = {}
        self._terminal_policy = TerminalPolicyConfig()
        self._async_invocations: dict[str, AsyncExecutionState] = {}
        self._apply_terminal_policy()

        resolved_config_path = self._resolve_config_path(config_path)
        if resolved_config_path is not None:
            self._load_config(resolved_config_path)

    def _resolve_config_path(self, config_path: str | None) -> Path | None:
        configured_path = (config_path or settings.ai_tools_config_path).strip()
        if configured_path:
            return Path(configured_path).expanduser().resolve()

        if self._DEFAULT_CONFIG_PATH.exists():
            return self._DEFAULT_CONFIG_PATH

        return None

    def _load_config(self, config_path: Path) -> None:
        if not config_path.exists():
            raise ValueError(f"tool config file not found: {config_path}")

        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("tool config must be a TOML table")

        enabled_tools = raw.get("enabled_tools")
        if enabled_tools is not None:
            if not isinstance(enabled_tools, list) or not all(
                isinstance(item, str) for item in enabled_tools
            ):
                raise ValueError("enabled_tools must be a list of strings")
            self._enabled_tools = {name.strip() for name in enabled_tools if name.strip()}

        routing = raw.get("routing")
        if routing is not None:
            if not isinstance(routing, dict):
                raise ValueError("routing must be an object")
            parsed_routing: dict[str, ToolRoutingConfig] = {}
            for tool_name, tool_routing in routing.items():
                if not isinstance(tool_name, str):
                    raise ValueError("routing keys must be tool names")
                if not isinstance(tool_routing, dict):
                    raise ValueError(f"routing for '{tool_name}' must be an object")

                timeout_seconds: float | None = None
                if "timeout_seconds" in tool_routing:
                    timeout_raw = tool_routing.get("timeout_seconds")
                    try:
                        timeout_seconds = float(timeout_raw)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"routing timeout_seconds for '{tool_name}' must be numeric"
                        ) from exc
                parsed_routing[tool_name.strip()] = ToolRoutingConfig(
                    timeout_seconds=timeout_seconds
                )

            self._routing = parsed_routing

        terminal_raw = raw.get("terminal")
        if terminal_raw is not None:
            if not isinstance(terminal_raw, dict):
                raise ValueError("terminal must be an object")
            blocked_commands_raw = terminal_raw.get("blocked_commands", [])
            if not isinstance(blocked_commands_raw, list) or not all(
                isinstance(item, str) for item in blocked_commands_raw
            ):
                raise ValueError("terminal.blocked_commands must be a list of strings")

            blocked_commands = tuple(
                command.strip() for command in blocked_commands_raw if command.strip()
            )
            self._terminal_policy = TerminalPolicyConfig(blocked_commands=blocked_commands)
            self._apply_terminal_policy()

    def _apply_terminal_policy(self) -> None:
        terminal_tool = tool_registry.get(TerminalCommandTool.name)
        if terminal_tool is None or not isinstance(terminal_tool, TerminalCommandTool):
            return
        terminal_tool.configure_blocked_commands(list(self._terminal_policy.blocked_commands))

    def _is_tool_enabled(self, name: str) -> bool:
        if self._enabled_tools is None:
            return True
        return name in self._enabled_tools

    def available_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for tool_name in tool_registry.all_names():
            if not self._is_tool_enabled(tool_name):
                continue
            tool = tool_registry.get(tool_name)
            if tool is not None:
                tools.append(tool)
        return tools

    def render_tool_catalog(self) -> str:
        lines = ["Available tools:"]
        for tool in self.available_tools():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    async def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._is_tool_enabled(name):
            raise ToolNotFoundError(f"tool not enabled: {name}")

        tool = tool_registry.get(name)
        if tool is None:
            raise ToolNotFoundError(f"tool not found: {name}")

        effective_arguments = dict(arguments or {})
        tool_routing = self._routing.get(name)
        if tool_routing is not None and tool_routing.timeout_seconds is not None:
            effective_arguments.setdefault("timeout_seconds", tool_routing.timeout_seconds)

        validated_arguments = tool.validate_arguments(effective_arguments)
        start = perf_counter()
        try:
            result = await tool.run(validated_arguments)
        except Exception:
            elapsed_ms = int((perf_counter() - start) * 1000)
            logger.exception("tool execution failed: name=%s duration_ms=%s", name, elapsed_ms)
            raise

        elapsed_ms = int((perf_counter() - start) * 1000)
        logger.info("tool execution succeeded: name=%s duration_ms=%s", name, elapsed_ms)
        return result

    async def execute_async(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        invocation_id = str(uuid.uuid4())
        task = asyncio.create_task(self.execute(name, arguments))
        self._async_invocations[invocation_id] = AsyncExecutionState(
            invocation_id=invocation_id,
            name=name,
            arguments=dict(arguments or {}),
            task=task,
        )
        return {
            "invocation_id": invocation_id,
            "name": name,
            "status": "running",
        }

    async def get_async_result(
        self,
        invocation_id: str,
        *,
        wait: bool = False,
        timeout_seconds: float | None = None,
        clear_after_read: bool = True,
    ) -> dict[str, Any]:
        state = self._async_invocations.get(invocation_id)
        if state is None:
            raise ToolNotFoundError(f"async invocation not found: {invocation_id}")

        if wait and not state.task.done():
            try:
                if timeout_seconds is None:
                    await state.task
                else:
                    await asyncio.wait_for(state.task, timeout_seconds)
            except TimeoutError:
                return {
                    "invocation_id": invocation_id,
                    "name": state.name,
                    "status": "running",
                }
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "invocation_id": invocation_id,
                    "name": state.name,
                    "status": "failed",
                    "error": str(exc),
                }
                if clear_after_read:
                    self._async_invocations.pop(invocation_id, None)
                return payload

        if not state.task.done():
            return {
                "invocation_id": invocation_id,
                "name": state.name,
                "status": "running",
            }

        try:
            result = state.task.result()
        except Exception as exc:  # noqa: BLE001
            payload = {
                "invocation_id": invocation_id,
                "name": state.name,
                "status": "failed",
                "error": str(exc),
            }
        else:
            payload = {
                "invocation_id": invocation_id,
                "name": state.name,
                "status": "completed",
                "result": result,
            }

        if clear_after_read:
            self._async_invocations.pop(invocation_id, None)
        return payload

    @staticmethod
    def format_result(name: str, result: dict[str, Any]) -> str:
        if name == "terminal":
            status = result.get("status")
            task_id = result.get("task_id")
            stdout = str(result.get("stdout", "")).rstrip()
            stderr = str(result.get("stderr", "")).rstrip()
            exit_code = result.get("exit_code")
            timed_out = result.get("timed_out")

            lines: list[str] = []
            if task_id is not None:
                lines.append(f"task_id: {task_id}")
            if status is not None:
                lines.append(f"status: {status}")
            lines.extend([f"exit_code: {exit_code}", f"timed_out: {timed_out}"])
            lines.append("stdout:")
            lines.append(stdout or "<empty>")
            lines.append("stderr:")
            lines.append(stderr or "<empty>")
            return "\n".join(lines)

        return json.dumps(result, ensure_ascii=False, indent=2)
