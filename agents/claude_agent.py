"""
Claude Code CLI Agent — wraps `claude -p` for non-interactive execution.
"""
from .base import BaseAgent


class ClaudeAgent(BaseAgent):
    name = "Claude Code"
    command = "claude"

    def build_args(self, prompt: str) -> list[str]:
        return ["-p", prompt, "--output-format", "text"]
