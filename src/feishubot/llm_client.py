from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx


class LLMClient(ABC):
    @abstractmethod
    async def generate_reply(self, prompt: str, user_id: str | None = None) -> str:
        raise NotImplementedError


class EchoLLMClient(LLMClient):
    async def generate_reply(self, prompt: str, user_id: str | None = None) -> str:
        prefix = f"[echo user={user_id}] " if user_id else "[echo] "
        return prefix + prompt


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        chat_path: str = "/v1/chat/completions",
        timeout_seconds: float = 60.0,
        default_system_prompt: str = "You are a helpful assistant.",
    ) -> None:
        if not base_url:
            raise ValueError("LLM_BASE_URL is required for openai_compatible provider")
        if not api_key:
            raise ValueError("LLM_API_KEY is required for openai_compatible provider")
        if not model:
            raise ValueError("LLM_MODEL is required for openai_compatible provider")

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._chat_path = chat_path if chat_path.startswith("/") else f"/{chat_path}"
        self._timeout_seconds = timeout_seconds
        self._default_system_prompt = default_system_prompt

    async def generate_reply(self, prompt: str, user_id: str | None = None) -> str:
        return await self.generate_reply_with_system_prompt(prompt=prompt, system_prompt=self._default_system_prompt, user_id=user_id)

    async def generate_reply_with_system_prompt(
        self,
        *,
        prompt: str,
        system_prompt: str,
        user_id: str | None = None,
    ) -> str:
        url = f"{self._base_url}{self._chat_path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        if user_id:
            payload["user"] = user_id

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        return self._extract_text(data)

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if not choices:
            raise RuntimeError(f"invalid LLM response, missing choices: {data}")

        first_choice = choices[0]
        message = first_choice.get("message", {})
        content = message.get("content")

        if isinstance(content, str):
            return content

        # Some providers return content blocks in list format.
        if isinstance(content, list):
            text_chunks: list[str] = []
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    text_value = chunk.get("text")
                    if isinstance(text_value, str):
                        text_chunks.append(text_value)
            if text_chunks:
                return "\n".join(text_chunks)

        raise RuntimeError(f"invalid LLM response, missing message content: {data}")
