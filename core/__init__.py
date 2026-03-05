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

    async def _route_by_nlu(self, text: str, user_id: int, cwd: str) -> Optional[str]:
        """Use Gemini to route natural language requests to the right skill (Fast Path)."""
        skills_info = self.get_all_skills_info()
        
        routing_prompt = (
            "You are a router. The user sent a natural language message.\n"
            "Here are the available skills and their commands:\n"
        )
        for s in skills_info:
            routing_prompt += f"- {s['name']}: {s['description']} (Commands: {', '.join(s['commands'])})\n"
            
        routing_prompt += (
            f"\nUser message: '{text}'\n"
            f"If the message clearly matches a skill's command, reply ONLY with the command and arguments.\n"
            f"If it's complex or general, return 'AUTONOMOUS'. Do not explain."
        )

        try:
            route_decision = await self.gemini.execute(routing_prompt, cwd)
            route_decision = route_decision.strip()
            
            if route_decision == "AUTONOMOUS" or not route_decision.startswith("/"):
                return None
                
            parts = route_decision.split()
            simulated_cmd = parts[0]
            simulated_args = parts[1:]
            
            skill: any = self.get_skill_for_command(simulated_cmd)
            if skill:
                logger.info(f"NLU Fast-Routed: '{text}' -> {route_decision}")
                return await skill.handle(simulated_cmd, simulated_args, user_id)
        except Exception as e:
            logger.error(f"NLU Fast-Routing failed: {e}")
            
        return None

    async def handle_text(self, text: str, user_id: int, cwd: str) -> str:
        """
        Handle free-text messages with an autonomous reasoning loop (ReAct).
        """
        # 1. Try simple NLU routing first for exact command matches (Fast Path)
        routed_result = await self._route_by_nlu(text, user_id, cwd)
        if routed_result is not None:
             return routed_result

        # 2. Enter Autonomous Reasoning Loop (Phase 3 with RAG)
        logger.info(f"Starting Autonomous Loop for user {user_id}: '{text[:50]}...'")
        
        # Retrieve Long-term Memory Context
        semantic_context = self.memory.semantic.search(text)
        if semantic_context:
            logger.info(f"Retrieved semantic context: {len(semantic_context)} chars")
            context_block = f"\nRelevant Context from Long-term Memory:\n{semantic_context}\n"
        else:
            context_block = ""

        # Prepare tool list
        skills_info = self.get_all_skills_info()
        skills_list = "\n".join([f"- {s['commands'][0]}: {s['description']}" for s in skills_info])
        
        # Build System Prompt
        system_prompt = (
            "You are an advanced AI Agent. Resolve the user's request efficiently.\n"
            "You have access to long-term memory and specific tools.\n\n"
            "Format your reasoning in steps:\n"
            "Thought: Your reasoning\n"
            "Action: /command args\n"
            "Final Answer: Final result for the user\n\n"
            f"Current Directory: {cwd}\n"
            f"{context_block}"
            f"Available Tools:\n{skills_list}\n\n"
            "Rules:\n"
            "1. Only use one Action at a time.\n"
            "2. Think if you need to remember something from the context provided.\n"
            "3. If no tools are needed, provide a Final Answer immediately.\n"
        )

        history = f"User: {text}\n"
        max_steps = 5
        
        for i in range(max_steps):
            full_prompt = f"{system_prompt}\n\n{history}\n"
            
            # Use Gemini to think/act
            response = await self.gemini.execute(full_prompt, cwd)
            logger.debug(f"Loop step {i+1} response: {response}")
            
            # Parse response
            if "Final Answer:" in response:
                final_answer = response.split("Final Answer:")[1].strip()
                # Save to memory and return
                self.memory.add_message(user_id, "user", text)
                self.memory.add_message(user_id, "assistant", final_answer[:500])
                return final_answer
            
            if "Action:" in response:
                action_line = [l for l in response.split("\n") if "Action:" in l][0]
                action_text = action_line.split("Action:")[1].strip()
                
                # Execute action
                parts = action_text.split()
                if not parts: continue
                command = parts[0]
                args = parts[1:]
                
                logger.info(f"Agent Action: {command} {args}")
                skill: any = self.get_skill_for_command(command)
                
                if skill:
                    try:
                        observation = await skill.handle(command, args, user_id)
                    except Exception as e:
                        observation = f"Error: {e}"
                else:
                    observation = f"Error: Unknown skill {command}"
                
                history += f"{response}\nObservation: {observation}\n"
                continue
            
            # If Gemini didn't follow format but provided text, assume it's the answer
            if i == 0 and not "Action:" in response:
                 return response
                 
            history += f"{response}\n"

        return "⚠️任務超時或無法完成目標。"
