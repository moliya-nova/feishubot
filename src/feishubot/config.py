from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ActiveLLMConfig:
    name: str
    provider: str
    base_url: str
    api_key: str
    model: str
    chat_path: str
    timeout_seconds: float
    system_prompt: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""

    llm_provider: str = "echo"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_chat_path: str = "/v1/chat/completions"
    llm_timeout_seconds: float = 60.0
    llm_system_prompt: str = "You are a helpful assistant."
    llm_active_model: str = ""
    llm_models_config_path: str = ""
    ai_tools_config_path: str = ""

    def _load_models_from_toml(self, config_path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
        if not config_path.exists():
            raise ValueError(f"LLM models config not found: {config_path}")

        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("LLM models config must be a TOML table")

        default_model = str(raw.get("default_model", "")).strip()
        models_raw = raw.get("models")
        if not isinstance(models_raw, dict) or not models_raw:
            raise ValueError("LLM models config must include a non-empty [models] table")

        models: dict[str, dict[str, Any]] = {}
        for model_name, model_config in models_raw.items():
            if not isinstance(model_name, str) or not model_name.strip():
                continue
            if not isinstance(model_config, dict):
                raise ValueError(f"model '{model_name}' must be a TOML table")
            models[model_name.strip()] = dict(model_config)

        if not models:
            raise ValueError("LLM models config does not define any valid models")

        return default_model, models

    def _resolve_from_model_map(self) -> ActiveLLMConfig | None:
        models_config_path = self.llm_models_config_path.strip()
        if not models_config_path:
            return None

        resolved_path = Path(models_config_path).expanduser().resolve()
        default_model, models = self._load_models_from_toml(resolved_path)

        active_name = self.llm_active_model.strip() or default_model or next(iter(models))
        active_config = models.get(active_name)
        if not isinstance(active_config, dict):
            raise ValueError(f"active model '{active_name}' not found in model config")

        provider = str(active_config.get("provider", "openai_compatible"))
        base_url = str(active_config.get("base_url", ""))
        api_key = str(active_config.get("api_key", ""))
        model = str(active_config.get("model", ""))
        chat_path = str(active_config.get("chat_path", "/v1/chat/completions"))
        timeout_seconds_raw = active_config.get("timeout_seconds", self.llm_timeout_seconds)
        system_prompt = str(active_config.get("system_prompt", self.llm_system_prompt))

        try:
            timeout_seconds = float(timeout_seconds_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"timeout_seconds for active model '{active_name}' must be a number"
            ) from exc

        return ActiveLLMConfig(
            name=active_name,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            chat_path=chat_path,
            timeout_seconds=timeout_seconds,
            system_prompt=system_prompt,
        )

    def active_llm_config(self) -> ActiveLLMConfig:
        model_map_config = self._resolve_from_model_map()
        if model_map_config is not None:
            return model_map_config

        return ActiveLLMConfig(
            name=self.llm_active_model.strip() or self.llm_model,
            provider=self.llm_provider,
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            model=self.llm_model,
            chat_path=self.llm_chat_path,
            timeout_seconds=self.llm_timeout_seconds,
            system_prompt=self.llm_system_prompt,
        )


settings = Settings()
