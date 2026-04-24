# src/core/memory/context.py
from __future__ import annotations
import tiktoken
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store

ROLE_PREFIXES = {
    "user": "USER",
    "assistant": "ASSISTANT",
    "system": "SYSTEM",
    "tool": "TOOL",
}

_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def format_turns_as_messages(turns: list[dict]) -> list[dict[str, str]]:
    """Convert stored turns into structured chat messages."""
    messages: list[dict[str, str]] = []
    for turn in turns:
        role = turn.get("role", "user")
        if role not in {"user", "assistant", "system", "tool"}:
            role = "user"
        messages.append({"role": role, "content": turn.get("content", "")})
    return messages


def render_turns_as_text(turns: list[dict]) -> str:
    """Render stored turns as a compact text block for CLI-style runners."""
    lines: list[str] = []
    for turn in turns:
        role = ROLE_PREFIXES.get(turn.get("role", "user"), "USER")
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines)


class ContextAssembler:
    """Builds context from Tier 1 permanent memory + Tier 3 history.

    Can render either:
      - text blocks for CLI-style runners
      - structured message lists for chat-style callers

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

    def _build_tier1_text(self, user_id: int, channel: str) -> str:
        entries = self._t1.list_entries(user_id, channel)
        if not entries:
            return ""
        # Build text entry-by-entry from most recent, stop before exceeding budget.
        # This avoids mid-sentence character-ratio slicing.
        selected: list[str] = []
        used = 0
        for entry in reversed(entries):
            line = f"- {entry['content']}"
            cost = count_tokens(line)
            if used + cost > self._t1_budget:
                break
            selected.insert(0, line)
            used += cost
        if not selected:
            return ""
        return "## Permanent Memory\n" + "\n".join(selected)

    async def _select_recent_turns(
        self, *, user_id: int, channel: str, recent_turns: int
    ) -> list[dict]:
        turns = await self._t3.get_recent(user_id=user_id, channel=channel, n=recent_turns)
        if not turns:
            return []

        selected: list[dict] = []
        used = 0
        for turn in reversed(turns):
            line = f"{ROLE_PREFIXES.get(turn['role'], turn['role'].upper())}: {turn['content']}"
            cost = count_tokens(line)
            if used + cost > self._t3_budget:
                break
            selected.insert(0, turn)
            used += cost
        return selected

    async def build(
        self, *, user_id: int, channel: str, recent_turns: int = 20
    ) -> str:
        sections: list[str] = []

        t1_text = self._build_tier1_text(user_id, channel)
        if t1_text:
            sections.append(t1_text)

        turns = await self._select_recent_turns(
            user_id=user_id, channel=channel, recent_turns=recent_turns
        )
        if turns:
            sections.append("## Conversation History\n" + render_turns_as_text(turns))

        return "\n\n".join(sections)

    async def build_messages(
        self, *, user_id: int, channel: str, recent_turns: int = 20
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []

        t1_text = self._build_tier1_text(user_id, channel)
        if t1_text:
            messages.append({"role": "system", "content": t1_text})

        turns = await self._select_recent_turns(
            user_id=user_id, channel=channel, recent_turns=recent_turns
        )
        messages.extend(format_turns_as_messages(turns))
        return messages
