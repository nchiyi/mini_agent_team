from .base import BaseAgent
from .gemini_agent import GeminiAgent
from .claude_agent import ClaudeAgent

AGENTS = {
    "gemini": GeminiAgent,
    "claude": ClaudeAgent,
}

__all__ = ["BaseAgent", "GeminiAgent", "ClaudeAgent", "AGENTS"]
