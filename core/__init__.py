"""
Core Engine — Central dispatcher for the Telegram AI Agent.
"""
import logging
import importlib
import pkgutil
import json
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

    async def _route_by_nlu(self, text: str, user_id: int, cwd: str) -> str:
        """Use Gemini to route natural language requests to the right skill."""
        skills_info = self.get_all_skills_info()
        
        # Build prompt for Gemini to decide routing
        routing_prompt = (
            "You are a router. The user sent a natural language message.\n"
            "Here are the available skills and their commands:\n"
        )
        for s in skills_info:
            if s['name'] == 'dev_agent': continue # Skip default
            routing_prompt += f"- {s['name']}: {s['description']} (Commands: {', '.join(s['commands'])})\n"
            
        routing_prompt += (
            f"\nUser message: '{text}'\n"
            f"If the message clearly matches a skill's intent (e.g. checking system status, searching news, tracking git projects), "
            f"reply ONLY with the corresponding command and any necessary arguments (e.g., '/sys', '/projects', '/news AI', '/install https://...').\n"
            f"If it's a general coding question, coding task, conversation, or ambiguous, return EXACTLY 'DEV_AGENT'. Do not explain."
        )

        try:
            route_decision = await self.gemini.execute(routing_prompt, cwd)
            route_decision = route_decision.strip()
            
            # Stop condition if not clearly routed
            if route_decision == "DEV_AGENT" or not route_decision.startswith("/"):
                return None
                
            # Parse the simulated command
            parts = route_decision.split()
            simulated_cmd = parts[0]
            simulated_args = parts[1:]
            
            skill = self.get_skill_for_command(simulated_cmd)
            if skill:
                logger.info(f"NLU Routed: '{text}' -> {route_decision}")
                # Execute the matched skill
                return await skill.handle(simulated_cmd, simulated_args, user_id)
                
        except Exception as e:
            logger.error(f"NLU Routing failed: {e}")
            
        return None

    async def handle_text(self, text: str, user_id: int, cwd: str) -> str:
        """Handle free-text messages — route via NLU or send to dev agent."""
        
        # Try NLU routing first
        routed_result = await self._route_by_nlu(text, user_id, cwd)
        if routed_result is not None:
             return routed_result
             
        # Fallback to general conversational Dev Agent
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
