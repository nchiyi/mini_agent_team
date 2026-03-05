"""
Gemini CLI Agent — wraps `gemini -p` for non-interactive execution.
"""
from .base import BaseAgent


class GeminiAgent(BaseAgent):
    name = "Gemini CLI"
    command = "gemini"

    def build_args(self, prompt: str) -> list[str]:
        return ["-p", prompt]
