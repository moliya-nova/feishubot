from __future__ import annotations

import json
from json import JSONDecodeError, JSONDecoder
from typing import Any

from feishubot.ai.core.schemas import ChatMessage
from feishubot.ai.providers.base import ModelProvider
from feishubot.ai.tools.runtime import ToolRuntime


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = [line for line in stripped.splitlines() if not line.startswith("```")]
    return "\n".join(lines).strip()


def _extract_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    payload_text = _strip_code_fences(text)

    payload = _parse_json_object(payload_text)
    if payload is None:
        return None

    tool_name = payload.get("tool") or payload.get("name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return None

    arguments = payload.get("arguments") or payload.get("args") or {}
    if not isinstance(arguments, dict):
        return None

    return tool_name.strip(), arguments


def _parse_json_object(text: str) -> dict[str, Any] | None:
    decoder = JSONDecoder()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except JSONDecodeError:
        pass

    for start in range(len(text)):
        if text[start] != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[start:])
        except JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


class AgentLoop:
    """Coordinates model calls and tool invocations."""

    _MAX_TOOL_TURNS = 6
    _MAX_RUNNING_POLLS_PER_TASK = 3
    _MAX_CONSECUTIVE_RUNNING_POLLS = 3

    def __init__(
        self,
        *,
        model_provider: ModelProvider,
        tool_runtime: ToolRuntime,
        system_prompt: str | None = None,
    ) -> None:
        self._model_provider = model_provider
        self._tool_runtime = tool_runtime
        self._system_prompt = system_prompt

    async def _generate_model_reply(self, *, prompt: str, user_id: str | None = None) -> str:
        messages: list[ChatMessage] = []
        if self._system_prompt:
            messages.append(ChatMessage(role="system", content=self._system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))

        response = await self._model_provider.chat(messages=messages, user_id=user_id)
        return response.text

    def _build_tool_routing_prompt(self, user_input: str) -> str:
        tool_catalog = self._tool_runtime.render_tool_catalog()
        return (
            "You can answer directly or call one tool.\n"
            f"{tool_catalog}\n\n"
            "If a tool is needed, respond with exactly one JSON object:\n"
            '{"tool": "terminal", "arguments": {"command": "df -h"}}\n\n'
            "For terminal tool, choose mode by scenario:\n"
            "- sync: run and wait for final output\n"
            "- start_async: submit long command and get task_id immediately\n"
            "- get_async_result: poll with task_id to check running/completed\n"
            "- cancel_async: cancel running task by task_id\n\n"
            "If no tool is needed, answer normally.\n\n"
            f"User request:\n{user_input}"
        )

    def _build_tool_followup_prompt(
        self,
        *,
        user_input: str,
        tool_history: list[dict[str, Any]],
        remaining_turns: int,
    ) -> str:
        history_lines: list[str] = []
        for idx, item in enumerate(tool_history, start=1):
            history_lines.append(f"Step {idx} tool: {item['tool_name']}")
            history_lines.append(
                "Step "
                f"{idx} arguments:\n{json.dumps(item['arguments'], ensure_ascii=False, indent=2)}"
            )
            history_lines.append(f"Step {idx} result:\n{item['formatted_result']}")
            history_lines.append(f"Step {idx} failed: {item['tool_failed']}")
            history_lines.append(f"Step {idx} error: {item['tool_error']}")
            history_lines.append("")

        history_text = "\n".join(history_lines).strip() or "<no tool calls yet>"

        return (
            "You can either answer now or call one more tool.\n"
            "If calling a tool, respond with exactly one JSON object only.\n"
            "If answering, do not output JSON.\n\n"
            f"Remaining tool-call turns: {remaining_turns}\n\n"
            f"Original user request:\n{user_input}\n\n"
            f"Tool call history:\n{history_text}\n\n"
            "Guidance for terminal async tasks:\n"
            "- If previous terminal result is status=running, call terminal with "
            "mode=get_async_result and the same task_id.\n"
            "- If status=completed, use stdout/stderr to answer.\n"
            "- Prefer sync mode for short commands and async mode for long-running commands."
        )

    async def run(self, user_input: str, user_id: str | None = None) -> str:
        tool_history: list[dict[str, Any]] = []
        prompt = self._build_tool_routing_prompt(user_input)
        running_poll_counts: dict[str, int] = {}
        consecutive_running_polls = 0
        forced_final_note = ""

        for turn in range(self._MAX_TOOL_TURNS):
            model_reply = await self._generate_model_reply(prompt=prompt, user_id=user_id)
            tool_call = _extract_tool_call(model_reply)
            if tool_call is None:
                return model_reply

            tool_name, arguments = tool_call
            tool_failed = False
            tool_error = ""
            try:
                tool_result = await self._tool_runtime.execute(tool_name, arguments)
                formatted_result = self._tool_runtime.format_result(tool_name, tool_result)
            except Exception as exc:  # noqa: BLE001
                tool_failed = True
                tool_error = str(exc)
                tool_result = {"error": tool_error}
                formatted_result = "<tool execution failed>"

            is_terminal_poll = (
                tool_name == "terminal"
                and str(arguments.get("mode", "")).strip().lower() == "get_async_result"
            )
            poll_task_id = str(arguments.get("task_id", "")).strip()
            tool_status = str(tool_result.get("status", "")).strip().lower()

            if is_terminal_poll and poll_task_id and tool_status == "running":
                consecutive_running_polls += 1
                running_poll_counts[poll_task_id] = running_poll_counts.get(poll_task_id, 0) + 1

                task_poll_count = running_poll_counts[poll_task_id]
                if (
                    task_poll_count > self._MAX_RUNNING_POLLS_PER_TASK
                    or consecutive_running_polls > self._MAX_CONSECUTIVE_RUNNING_POLLS
                ):
                    forced_final_note = (
                        "Polling guard triggered: async terminal task remained "
                        "running for too many checks. The loop stopped further "
                        "polling to avoid getting stuck."
                    )
                    try:
                        cancel_result = await self._tool_runtime.execute(
                            "terminal",
                            {"mode": "cancel_async", "task_id": poll_task_id},
                        )
                    except Exception as exc:  # noqa: BLE001
                        cancel_formatted_result = f"<auto-cancel failed: {exc}>"
                        cancel_failed = True
                        cancel_error = str(exc)
                    else:
                        cancel_formatted_result = self._tool_runtime.format_result(
                            "terminal", cancel_result
                        )
                        cancel_failed = False
                        cancel_error = ""

                    tool_history.append(
                        {
                            "tool_name": "terminal",
                            "arguments": {"mode": "cancel_async", "task_id": poll_task_id},
                            "formatted_result": cancel_formatted_result,
                            "tool_failed": cancel_failed,
                            "tool_error": cancel_error,
                        }
                    )
                    break
            else:
                consecutive_running_polls = 0

            tool_history.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "formatted_result": formatted_result,
                    "tool_failed": tool_failed,
                    "tool_error": tool_error,
                }
            )

            remaining_turns = self._MAX_TOOL_TURNS - turn - 1
            prompt = self._build_tool_followup_prompt(
                user_input=user_input,
                tool_history=tool_history,
                remaining_turns=remaining_turns,
            )

            if forced_final_note:
                break

        final_prompt = (
            self._build_tool_followup_prompt(
                user_input=user_input,
                tool_history=tool_history,
                remaining_turns=0,
            )
            + "\n\n"
            + (forced_final_note + "\n\n" if forced_final_note else "")
            + "Do not call any more tools. Answer the user directly now."
        )
        return await self._generate_model_reply(prompt=final_prompt, user_id=user_id)
