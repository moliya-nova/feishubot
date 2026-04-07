from __future__ import annotations


class MemoryStore:
    """State store abstraction scaffold."""

    async def append(self, key: str, value: str) -> None:
        raise NotImplementedError("Scaffold only. Implement state persistence here.")

    async def read(self, key: str) -> list[str]:
        raise NotImplementedError("Scaffold only. Implement state retrieval here.")
