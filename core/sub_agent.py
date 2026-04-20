"""
Sub-Agent — Independent AI agents with their own sessions.

Each sub-agent has its own conversation history, system prompt,
and can use a different model. Use cases:
  - Router Agent (fast, cheap model for intent classification)
  - Dev Agent (powerful model for code generation)
  - Summary Agent (mid-tier model for summarization)
"""
import json
import logging
import os
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
        self.history_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", f"subagent_{name}_history.json")
        self.history: list[dict] = self._load_history()

    def _load_history(self) -> list[dict]:
        try:
            if os.path.exists(self.history_path):
                with open(self.history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
        except Exception:
            logger.warning("Failed to load sub-agent history", exc_info=True)
        return []

    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(self.history[-20:], f, ensure_ascii=False, indent=2)
        except Exception:
            logger.warning("Failed to persist sub-agent history", exc_info=True)

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
        self._save_history()

        usage_tokens = response.usage.total_tokens if hasattr(response, 'usage') and response.usage else '?'
        logger.info(f"SubAgent[{self.name}] responded ({usage_tokens} tokens)")
        return message_content

    def reset(self):
        """Clear conversation history."""
        self.history.clear()
        self._save_history()
        logger.info(f"SubAgent[{self.name}] history cleared")
