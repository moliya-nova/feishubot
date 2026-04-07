from feishubot.ai.providers.base import ModelProvider


class AnthropicProvider(ModelProvider):
    """Placeholder provider implementation."""

    async def chat(self, messages, *, user_id=None):  # type: ignore[override]
        raise NotImplementedError("Scaffold only. Implement provider call logic here.")
