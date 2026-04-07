from __future__ import annotations


class AgentLoop:
    """Coordinates model calls and tool invocations (scaffold)."""

    async def run(self, user_input: str, user_id: str | None = None) -> str:
        raise NotImplementedError("Scaffold only. Implement agent loop here.")
