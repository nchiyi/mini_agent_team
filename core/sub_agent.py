"""
Sub-Agent — Independent AI agents with their own sessions.

Each sub-agent has its own conversation history, system prompt,
and can use a different model. Use cases:
  - Router Agent (fast, cheap model for intent classification)
  - Dev Agent (powerful model for code generation)
  - Summary Agent (mid-tier model for summarization)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SubAgent:
    """An independent AI agent with its own conversation state."""

    def __init__(self, name: str, system_prompt: str,
                 model: Optional[str], gemini_client):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.gemini = gemini_client
        self.history: list[dict] = []  # Simple in-memory history

    async def send(self, message: str) -> str:
        """Send a message to this sub-agent and get a response."""
        # Build context from history
        context_lines = []
        for entry in self.history[-10:]:  # Keep last 10 turns
            context_lines.append(f"{entry['role']}: {entry['content']}")

        if context_lines:
            full_prompt = "\n".join(context_lines) + f"\nUser: {message}"
        else:
            full_prompt = message

        response, usage = await self.gemini.generate(
            full_prompt,
            model=self.model,
            system_instruction=self.system_prompt,
        )

        # Store in history
        self.history.append({"role": "User", "content": message})
        self.history.append({"role": "Assistant", "content": response[:500]})

        logger.info(f"SubAgent[{self.name}] responded ({usage.get('total_tokens', '?')} tokens)")
        return response

    def reset(self):
        """Clear conversation history."""
        self.history.clear()
        logger.info(f"SubAgent[{self.name}] history cleared")
