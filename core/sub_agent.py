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
                 model: Optional[str], ollama_client):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model or "llama3.1"
        self.client = ollama_client
        self.history: list[dict] = []  # Simple in-memory history

    async def send(self, message: str) -> str:
        """Send a message to this sub-agent and get a response."""
        # Build context from history
        messages = [{"role": "system", "content": self.system_prompt}]
        
        for entry in self.history[-10:]:  # Keep last 10 turns
            messages.append({"role": entry['role'], "content": entry['content']})

        messages.append({"role": "user", "content": message})

        response = await self.client.generate(
            messages=messages,
            model=self.model,
        )
        
        message_content = response.choices[0].message.content or ""

        # Store in history
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": message_content[:500]})

        usage_tokens = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else '?'
        logger.info(f"SubAgent[{self.name}] responded ({usage_tokens} tokens)")
        return message_content

    def reset(self):
        """Clear conversation history."""
        self.history.clear()
        logger.info(f"SubAgent[{self.name}] history cleared")
