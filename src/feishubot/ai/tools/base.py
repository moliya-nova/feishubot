from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
