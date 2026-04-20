# src/core/memory/context.py
from __future__ import annotations
import tiktoken
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store

_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


class ContextAssembler:
    """Builds a context string from Tier 1 permanent memory + Tier 3 history.

    Sections (in order of priority):
      1. Tier 1 permanent memory  (≤ tier1_budget tokens)
      2. Tier 3 recent history    (≤ tier3_budget tokens, most recent first)
    Total hard cap: max_tokens.
    """

    def __init__(
        self,
        tier1: Tier1Store,
        tier3: Tier3Store,
        max_tokens: int = 4000,
        tier1_budget: int = 800,
        tier3_budget: int = 2000,
    ):
        self._t1 = tier1
        self._t3 = tier3
        self._max = max_tokens
        self._t1_budget = min(tier1_budget, max_tokens)
        self._t3_budget = min(tier3_budget, max_tokens - self._t1_budget)

    async def build(
        self, *, user_id: int, channel: str, recent_turns: int = 20
    ) -> str:
        sections: list[str] = []

        # --- Tier 1 ---
        t1_text = self._t1.render_for_context(user_id, channel)
        if t1_text:
            if count_tokens(t1_text) <= self._t1_budget:
                sections.append(t1_text)
            else:
                # Truncate to budget (character approximation)
                ratio = self._t1_budget / count_tokens(t1_text)
                sections.append(t1_text[: int(len(t1_text) * ratio)])

        # --- Tier 3 ---
        turns = await self._t3.get_recent(user_id=user_id, channel=channel, n=recent_turns)
        if turns:
            history_lines = []
            used = 0
            for turn in reversed(turns):  # iterate newest-first, insert at front
                line = f"{turn['role'].upper()}: {turn['content']}"
                cost = count_tokens(line)
                if used + cost > self._t3_budget:
                    break
                history_lines.insert(0, line)
                used += cost
            if history_lines:
                sections.append("## Conversation History\n" + "\n".join(history_lines))

        return "\n\n".join(sections)
