"""
Base Skill — Abstract class for all skills.
"""
from abc import ABC, abstractmethod
from typing import Optional, Any


class BaseSkill(ABC):
    """Base class for all skills."""

    name: str = "base"
    description: str = ""
    commands: list[str] = []
    schedule: Optional[str] = None  # Cron expression for periodic tasks

    def __init__(self):
        self.engine = None  # Set by engine on registration

    @abstractmethod
    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        """
        Handle a Telegram command.

        Args:
            command: The /command that triggered this
            args: Arguments after the command
            user_id: Telegram user ID

        Returns:
            Response text to send back
        """
        ...

    async def scheduled_task(self) -> None:
        """Override for periodic scheduled tasks."""
        pass

    def get_help(self) -> str:
        """Return help text for this skill."""
        cmds = ", ".join(f"`{c}`" for c in self.commands)
        return f"**{self.name}** — {self.description}\n指令: {cmds}"

    def get_tool_spec(self) -> dict[str, Any]:
        """
        Return the OpenAI-compatible function calling spec for this skill.
        Default implementation uses a single 'args' string.
        """
        cmd = self.commands[0].lstrip("/") if self.commands else self.name
        return {
            "type": "function",
            "function": {
                "name": cmd,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "string",
                            "description": "參數字串（例如搜尋關鍵字或 URL）"
                        }
                    },
                    "required": ["args"] if self.name not in ["usage_stats", "system_monitor"] else []
                }
            }
        }
