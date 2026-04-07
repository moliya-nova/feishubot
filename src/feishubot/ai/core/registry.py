from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class NamedRegistry(Generic[T]):
    """Simple in-memory name-to-instance registry used by providers/tools."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def register(self, name: str, item: T) -> None:
        self._items[name] = item

    def get(self, name: str) -> T | None:
        return self._items.get(name)

    def all_names(self) -> list[str]:
        return sorted(self._items.keys())
