"""
Core Engine — Central dispatcher for the Telegram AI Agent.
"""
import logging
import importlib
import pkgutil
from typing import Optional

logger = logging.getLogger(__name__)


class Engine:
    """Central engine that manages skills, Gemini CLI, and routing."""

    def __init__(self, gemini, memory, scheduler=None):
        self.gemini = gemini
        self.memory = memory
        self.scheduler = scheduler
        self.skills: dict = {}
        self.command_map: dict = {}  # /command → skill

    def register_skill(self, skill):
        """Register a skill and map its commands."""
        self.skills[skill.name] = skill
        skill.engine = self
        for cmd in skill.commands:
            self.command_map[cmd] = skill
        logger.info(f"Registered skill: {skill.name} (commands: {skill.commands})")

        # Register scheduled tasks
        if self.scheduler and skill.schedule and hasattr(skill, "scheduled_task"):
            self.scheduler.add_cron_job(
                skill.name, skill.schedule, skill.scheduled_task
            )
            logger.info(f"Scheduled task for {skill.name}: {skill.schedule}")

    def get_skill_for_command(self, command: str) -> Optional[object]:
        """Find the skill that handles a given command."""
        return self.command_map.get(command)

    def get_all_skills_info(self) -> list[dict]:
        """Get info about all registered skills."""
        result = []
        for name, skill in self.skills.items():
            result.append({
                "name": name,
                "description": skill.description,
                "commands": skill.commands,
            })
        return result

    async def handle_text(self, text: str, user_id: int, cwd: str) -> str:
        """Handle free-text messages — send to Gemini CLI."""
        # Add context from memory
        context = self.memory.get_context(user_id)
        if context:
            enhanced_prompt = f"Context:\n{context}\n\nUser request:\n{text}"
        else:
            enhanced_prompt = text

        result = await self.gemini.execute(enhanced_prompt, cwd)

        # Save to memory
        self.memory.add_message(user_id, "user", text)
        self.memory.add_message(user_id, "assistant", result[:500])

        return result
