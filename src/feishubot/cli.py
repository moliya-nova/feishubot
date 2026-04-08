from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from feishubot.app import get_llm_client
from feishubot.config import settings
from feishubot.llm_client import OpenAICompatibleLLMClient

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
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        values[key] = value
    return values


def _format_env_value(value: str) -> str:
    needs_quote = any(ch.isspace() for ch in value) or any(ch in value for ch in ["#", '"', "'"])
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
        "LLM_MODELS_JSON",
    ]

    lines = [f"{key}={_format_env_value(values.get(key, ''))}" for key in keys_in_order]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_models_json(raw: str) -> dict[str, dict[str, str]]:
    value = raw.strip()
    if not value:
        return {}

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    models: dict[str, dict[str, str]] = {}
    for name, config in parsed.items():
        if isinstance(name, str) and isinstance(config, dict):
            models[name] = {k: str(v) for k, v in config.items()}
    return models


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
        "LLM_MODELS_JSON": current.get("LLM_MODELS_JSON", ""),
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

        models = _parse_models_json(current.get("LLM_MODELS_JSON", ""))
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
        values["LLM_MODELS_JSON"] = json.dumps(models, ensure_ascii=True)

        print("Applied model preset:")
        print(f"  provider: {selected_preset_key}")
        print(f"  base_url: {values['LLM_BASE_URL']}")
        print(f"  model: {values['LLM_MODEL']}")
        print(f"  chat_path: {values['LLM_CHAT_PATH']}")
        print(f"  active_model: {values['LLM_ACTIVE_MODEL']}")

    if provider_value == "echo":
        values["LLM_ACTIVE_MODEL"] = ""
        values["LLM_MODELS_JSON"] = ""

    env_path.parent.mkdir(parents=True, exist_ok=True)
    _write_env_file(env_path, values)

    print("\nSetup complete.")
    print("Next steps:")
    print("  1) Start chat: feishubot chat")
    print("  2) Start gateway: feishubot gateway --reload")


async def _chat_loop(user_id: str, system_prompt: str | None) -> None:
    active = settings.active_llm_config()
    llm_client = get_llm_client()

    print("FeishuBot terminal chat is ready.")
    if active.provider == "echo":
        print("Using model: echo")
    else:
        print(f"Using model: {active.model}")
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
            if isinstance(llm_client, OpenAICompatibleLLMClient) and system_prompt:
                reply = await llm_client.generate_reply_with_system_prompt(
                    prompt=user_input,
                    system_prompt=system_prompt,
                    user_id=user_id,
                )
            else:
                reply = await llm_client.generate_reply(prompt=user_input, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            print(f"bot(error)> {exc}")
            continue

        print(f"bot> {reply}")


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

    parser.print_help()


def chat_main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run FeishuBot chat in terminal")
    _add_chat_arguments(parser)
    args = parser.parse_args(argv)
    _run_chat(args)


if __name__ == "__main__":
    main()
