# src/runners/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseRunner(ABC):
    @abstractmethod
    def run(
        self,
        prompt: str,
        user_id: int,
        channel: str,
        cwd: str,
        attachments: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """Yield text chunks as the runner produces output."""
        ...
