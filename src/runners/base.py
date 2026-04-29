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
        role_prefix: str = "",
    ) -> AsyncIterator[str]:
        """Yield text chunks as the runner produces output.

        ``role_prefix`` is the active-role identity/rules text the dispatcher
        wants prepended to the user's prompt. Subclasses choose how to inject
        it: ACPRunner sends it as a separate cache-controlled content block,
        CLI-style runners prepend it to the single prompt string.
        """
        ...
