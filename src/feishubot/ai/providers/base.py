from __future__ import annotations

from abc import ABC, abstractmethod

from feishubot.ai.core.schemas import ChatMessage, ModelResponse


class ModelProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[ChatMessage], *, user_id: str | None = None) -> ModelResponse:
        raise NotImplementedError
