from __future__ import annotations

import argparse
import asyncio
import json
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from feishubot.ai.orchestrator.agent_loop import AgentLoop
from feishubot.ai.providers import create_active_provider
from feishubot.ai.tools import ToolRuntime
from feishubot.config import settings

LLM_PRESETS: dict[str, dict[str, str]] = {
    "qwen": {
        "label": "Qwen (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com",
        "model": "qwen-plus",
        "chat_path": "/compatible-mode/v1/chat/completions",
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn",
        "model": "moonshot-v1-8k",
        "chat_path": "/v1/chat/completions",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "chat_path": "/v1/chat/completions",
    },
}


def _add_chat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--user-id", default="terminal-user", help="User ID passed to the LLM backend"
    )
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="Optional system prompt (only works with openai_compatible provider)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FeishuBot command line")
    subparsers = parser.add_subparsers(dest="command")

    chat_parser = subparsers.add_parser("chat", help="Start terminal chat loop")
    _add_chat_arguments(chat_parser)

    gateway_parser = subparsers.add_parser("gateway", help="Start HTTP gateway service")
    gateway_parser.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104 - intentional default for dev/container access
        help="Gateway bind host",
    )
    gateway_parser.add_argument("--port", type=int, default=8000, help="Gateway bind port")
    gateway_parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )

    setup_parser = subparsers.add_parser("setup", help="Interactive quick setup for .env")
    setup_parser.add_argument(
        "--env-file", default=".env", help="Path to the environment file to create/update"
    )
    setup_parser.add_argument(
        "--yes", action="store_true", help="Skip overwrite confirmation if env file exists"
    )

    model_parser = subparsers.add_parser(
        "model", help="List configured models and switch active model"
    )
    model_parser.add_argument(
        "--env-file", default=".env", help="Path to the environment file to update"
    )
    model_parser.add_argument(
        "--use",
        default=None,
        help="Switch directly to a model name without interactive prompt",
    )

    return parser


def _prompt_text(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if value:
        return value
    return default


def _prompt_secret(label: str, default: str = "") -> str:
    masked = "***" if default else ""
    suffix = f" [{masked}]" if masked else ""
    value = input(f"{label}{suffix}: ").strip()
    if value:
        return value
    return default


def _prompt_choice(label: str, options: list[tuple[str, str]], default_key: str) -> str:
    print(label)
    for key, desc in options:
        marker = " (default)" if key == default_key else ""
        print(f"  {key}) {desc}{marker}")

    valid_keys = {key for key, _ in options}
    while True:
        value = input("Choose: ").strip() or default_key
        if value in valid_keys:
            return value
        print(f"Invalid choice: {value}")


def _prompt_yes_no(label: str, default: bool = True) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        value = input(f"{label} [{default_text}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print(f"Invalid choice: {value}")


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            i += 1
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value.startswith(('"', "'")):
            quote = value[0]
            if not (len(value) >= 2 and value.endswith(quote)):
                collected = [value]
                j = i + 1
                while j < len(lines):
                    collected.append(lines[j])
                    if lines[j].rstrip().endswith(quote):
                        break
                    j += 1
                value = "\n".join(collected)
                i = j

        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif value.startswith("'") and value.endswith("'") and len(value) >= 2:
            value = value[1:-1]

        values[key] = value
        i += 1

    return values


def _format_env_value(value: str) -> str:
    needs_quote = any(ch.isspace() for ch in value) or any(ch in value for ch in ["#", '"', "'"])
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_env_assignment(key: str, value: str) -> str:
    return f"{key}={_format_env_value(value)}"


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    keys_in_order = [
        "APP_ENV",
        "LOG_LEVEL",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_VERIFICATION_TOKEN",
        "FEISHU_ENCRYPT_KEY",
        "LLM_PROVIDER",
        "LLM_ACTIVE_MODEL",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "LLM_CHAT_PATH",
        "LLM_TIMEOUT_SECONDS",
        "LLM_SYSTEM_PROMPT",
        "LLM_MODELS_CONFIG_PATH",
        "AI_TOOLS_CONFIG_PATH",
    ]

    lines = [_format_env_assignment(key, values.get(key, "")) for key in keys_in_order]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_models_config_path(config_value: str, env_path: Path) -> Path:
    raw = config_value.strip() or "models.toml"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (env_path.parent / path).resolve()
    else:
        path = path.resolve()
    return path


def _load_models_config(path: Path) -> tuple[str, dict[str, dict[str, str]]]:
    if not path.exists():
        return "", {}

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return "", {}

    if not isinstance(raw, dict):
        return "", {}

    default_model = str(raw.get("default_model", "")).strip()
    models_raw = raw.get("models")
    if not isinstance(models_raw, dict):
        return default_model, {}

    models: dict[str, dict[str, str]] = {}
    for name, config in models_raw.items():
        if not isinstance(name, str) or not isinstance(config, dict):
            continue
        model_name = name.strip()
        if not model_name:
            continue
        models[model_name] = {k: str(v) for k, v in config.items()}

    return default_model, models


def _escape_toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _dump_models_config(default_model: str, models: dict[str, dict[str, str]]) -> str:
    lines: list[str] = []
    if default_model.strip():
        lines.append(f"default_model = {_escape_toml_string(default_model.strip())}")
        lines.append("")

    for model_name, config in models.items():
        lines.append(f"[models.{_escape_toml_string(model_name)}]")
        ordered_fields = [
            "provider",
            "base_url",
            "api_key",
            "model",
            "chat_path",
            "timeout_seconds",
            "system_prompt",
        ]
        for field_name in ordered_fields:
            if field_name in config:
                lines.append(f"{field_name} = {_escape_toml_string(str(config[field_name]))}")

        for field_name, field_value in config.items():
            if field_name not in ordered_fields:
                lines.append(f"{field_name} = {_escape_toml_string(str(field_value))}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_models_config(path: Path, default_model: str, models: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_models_config(default_model, models), encoding="utf-8")


def _run_setup(args: argparse.Namespace) -> None:
    env_path = Path(args.env_file).expanduser().resolve()
    current = _load_env_file(env_path)

    print("FeishuBot quick setup")
    print(f"Target env file: {env_path}")

    if env_path.exists() and not args.yes:
        should_overwrite = _prompt_yes_no("Env file exists, update it", default=True)
        if not should_overwrite:
            print("Setup cancelled.")
            return

    model_choice = _prompt_choice(
        "Choose model provider",
        options=[
            ("1", f"qwen - {LLM_PRESETS['qwen']['label']}"),
            ("2", f"kimi - {LLM_PRESETS['kimi']['label']}"),
            ("3", f"deepseek - {LLM_PRESETS['deepseek']['label']}"),
            ("4", "echo (for local smoke testing)"),
        ],
        default_key="4" if current.get("LLM_PROVIDER") == "echo" else "1",
    )

    selected_preset_key = ""
    if model_choice == "1":
        selected_preset_key = "qwen"
    elif model_choice == "2":
        selected_preset_key = "kimi"
    elif model_choice == "3":
        selected_preset_key = "deepseek"

    provider_value = "echo" if model_choice == "4" else "openai_compatible"

    values: dict[str, str] = {
        "APP_ENV": _prompt_text("APP_ENV", current.get("APP_ENV", "dev")),
        "LOG_LEVEL": _prompt_text("LOG_LEVEL", current.get("LOG_LEVEL", "INFO")),
        # Keep Feishu fields untouched during quick setup.
        "FEISHU_APP_ID": current.get("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": current.get("FEISHU_APP_SECRET", ""),
        "FEISHU_VERIFICATION_TOKEN": current.get("FEISHU_VERIFICATION_TOKEN", ""),
        "FEISHU_ENCRYPT_KEY": current.get("FEISHU_ENCRYPT_KEY", ""),
        "LLM_PROVIDER": provider_value,
        "LLM_ACTIVE_MODEL": current.get("LLM_ACTIVE_MODEL", ""),
        "LLM_BASE_URL": current.get("LLM_BASE_URL", ""),
        "LLM_API_KEY": "",
        "LLM_MODEL": current.get("LLM_MODEL", ""),
        "LLM_CHAT_PATH": current.get("LLM_CHAT_PATH", "/v1/chat/completions"),
        "LLM_TIMEOUT_SECONDS": current.get("LLM_TIMEOUT_SECONDS", "60"),
        "LLM_SYSTEM_PROMPT": current.get("LLM_SYSTEM_PROMPT", "You are a helpful assistant."),
        "LLM_MODELS_CONFIG_PATH": current.get("LLM_MODELS_CONFIG_PATH", "models.toml"),
        "AI_TOOLS_CONFIG_PATH": current.get("AI_TOOLS_CONFIG_PATH", ""),
    }

    if provider_value == "openai_compatible":
        preset = LLM_PRESETS[selected_preset_key]
        values["LLM_BASE_URL"] = preset["base_url"]
        values["LLM_MODEL"] = preset["model"]
        values["LLM_CHAT_PATH"] = preset["chat_path"]
        values["LLM_API_KEY"] = _prompt_secret("LLM_API_KEY", current.get("LLM_API_KEY", ""))
        values["LLM_TIMEOUT_SECONDS"] = _prompt_text(
            "LLM_TIMEOUT_SECONDS", current.get("LLM_TIMEOUT_SECONDS", "60")
        )
        values["LLM_SYSTEM_PROMPT"] = _prompt_text(
            "LLM_SYSTEM_PROMPT",
            current.get("LLM_SYSTEM_PROMPT", "You are a helpful assistant."),
        )

        models_config_path = _resolve_models_config_path(values["LLM_MODELS_CONFIG_PATH"], env_path)
        _, models = _load_models_config(models_config_path)
        models[selected_preset_key] = {
            "provider": "openai_compatible",
            "base_url": values["LLM_BASE_URL"],
            "api_key": values["LLM_API_KEY"],
            "model": values["LLM_MODEL"],
            "chat_path": values["LLM_CHAT_PATH"],
            "timeout_seconds": values["LLM_TIMEOUT_SECONDS"],
            "system_prompt": values["LLM_SYSTEM_PROMPT"],
        }
        values["LLM_ACTIVE_MODEL"] = selected_preset_key
        _write_models_config(models_config_path, selected_preset_key, models)

        print("Applied model preset:")
        print(f"  provider: {selected_preset_key}")
        print(f"  base_url: {values['LLM_BASE_URL']}")
        print(f"  model: {values['LLM_MODEL']}")
        print(f"  chat_path: {values['LLM_CHAT_PATH']}")
        print(f"  active_model: {values['LLM_ACTIVE_MODEL']}")

    if provider_value == "echo":
        values["LLM_ACTIVE_MODEL"] = ""
        values["LLM_MODELS_CONFIG_PATH"] = ""

    env_path.parent.mkdir(parents=True, exist_ok=True)
    _write_env_file(env_path, values)

    print("\nSetup complete.")
    print("Next steps:")
    print("  1) Start chat: feishubot chat")
    print("  2) Start gateway: feishubot gateway --reload")


def _run_model_switch(args: argparse.Namespace) -> None:
    env_path = Path(args.env_file).expanduser().resolve()
    current = _load_env_file(env_path)
    models_config_value = current.get("LLM_MODELS_CONFIG_PATH", "models.toml")
    models_config_path = _resolve_models_config_path(models_config_value, env_path)
    default_model, models = _load_models_config(models_config_path)

    if not models:
        print(f"No models found in: {models_config_path}")
        print("Run 'feishubot setup' first.")
        return

    model_names = list(models.keys())
    active = current.get("LLM_ACTIVE_MODEL", "") or default_model
    if active not in models:
        active = model_names[0]

    print(f"Target env file: {env_path}")
    print("Available models:")
    for idx, name in enumerate(model_names, start=1):
        config = models[name]
        model_id = config.get("model", "")
        marker = " (active)" if name == active else ""
        print(f"  {idx}) {name} -> {model_id}{marker}")

    selected_name = args.use
    if selected_name is None:
        default_index = model_names.index(active) + 1
        selected_index = _prompt_choice(
            "Choose active model",
            options=[(str(i), n) for i, n in enumerate(model_names, start=1)],
            default_key=str(default_index),
        )
        selected_name = model_names[int(selected_index) - 1]

    if selected_name not in models:
        print(f"Model not found: {selected_name}")
        print("Use one of:", ", ".join(model_names))
        return

    selected_config = models[selected_name]
    current["LLM_ACTIVE_MODEL"] = selected_name
    current["LLM_PROVIDER"] = selected_config.get("provider", "openai_compatible")
    current["LLM_BASE_URL"] = selected_config.get("base_url", "")
    current["LLM_API_KEY"] = selected_config.get("api_key", "")
    current["LLM_MODEL"] = selected_config.get("model", "")
    current["LLM_CHAT_PATH"] = selected_config.get("chat_path", "/v1/chat/completions")
    current["LLM_TIMEOUT_SECONDS"] = selected_config.get("timeout_seconds", "60")
    current["LLM_SYSTEM_PROMPT"] = selected_config.get(
        "system_prompt", "You are a helpful assistant."
    )
    current["LLM_MODELS_CONFIG_PATH"] = models_config_value
    _write_models_config(models_config_path, selected_name, models)

    _write_env_file(env_path, current)

    print(f"Active model switched to: {selected_name}")
    print("Restart 'feishubot chat' or gateway to apply the new model.")


def _parse_direct_tool_command(user_input: str) -> tuple[str, dict[str, Any]] | None:
    stripped = user_input.strip()
    if stripped.startswith("/terminal ") or stripped.startswith("/shell "):
        command = stripped.split(" ", 1)[1].strip()
        return "terminal", {"command": command}

    if not stripped.startswith("/tool "):
        return None

    remainder = stripped.split(" ", 1)[1].strip()
    if not remainder:
        return None
    if " " not in remainder:
        return remainder, {}

    tool_name, payload_text = remainder.split(" ", 1)
    payload_text = payload_text.strip()
    if payload_text.startswith("{"):
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {"command": payload_text}
        if isinstance(payload, dict):
            return tool_name, payload

    if tool_name == "calculator":
        return tool_name, {"expression": payload_text}
    return tool_name, {"command": payload_text}


async def _chat_loop(user_id: str, system_prompt: str | None) -> None:
    active = settings.active_llm_config()
    model_provider = create_active_provider()
    tool_runtime = ToolRuntime()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=tool_runtime,
        system_prompt=system_prompt or active.system_prompt,
    )

    print("FeishuBot terminal chat is ready.")
    if active.provider == "echo":
        print("Using model: echo")
    else:
        print(f"Using model: {active.model}")
    print("Tool shortcuts: /terminal <command>, /tool <name> <payload>")
    print("Type your message and press Enter. Use /exit to quit.")

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not user_input:
            continue

        if user_input.lower() in {"/exit", "exit", "quit"}:
            print("bye")
            break

        try:
            direct_tool_call = _parse_direct_tool_command(user_input)
            if direct_tool_call is not None:
                tool_name, arguments = direct_tool_call
                tool_result = await tool_runtime.execute(tool_name, arguments)
                print(f"bot> {tool_runtime.format_result(tool_name, tool_result)}")
                continue

            final_reply = await agent_loop.run(user_input=user_input, user_id=user_id)
            print(f"bot> {final_reply}")
        except Exception as exc:  # noqa: BLE001
            print(f"bot(error)> {exc}")
            continue


def _run_chat(args: argparse.Namespace) -> None:
    asyncio.run(_chat_loop(user_id=args.user_id, system_prompt=args.system_prompt))


def _run_gateway(args: argparse.Namespace) -> None:
    import uvicorn

    if args.reload:
        print("Starting FeishuBot gateway in reload mode.")
    else:
        print("Starting FeishuBot gateway.")
    print(f"URL: http://{args.host}:{args.port}")
    uvicorn.run(
        "feishubot.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "chat":
        _run_chat(args)
        return

    if args.command == "gateway":
        _run_gateway(args)
        return

    if args.command == "setup":
        _run_setup(args)
        return

    if args.command == "model":
        _run_model_switch(args)
        return

    parser.print_help()


def chat_main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run FeishuBot chat in terminal")
    _add_chat_arguments(parser)
    args = parser.parse_args(argv)
    _run_chat(args)


if __name__ == "__main__":
    main()
