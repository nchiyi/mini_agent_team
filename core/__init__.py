"""
Core Engine — Central dispatcher for the Telegram AI Agent.

Uses Google GenAI SDK with native Function Calling for
intelligent routing and multi-step reasoning.
"""
import logging
from typing import Optional

from google.genai import types

logger = logging.getLogger(__name__)


class Engine:
    """Central engine that manages skills, Gemini client, and routing."""

    def __init__(self, gemini, memory, scheduler=None):
        self.gemini = gemini
        self.memory = memory
        self.scheduler = scheduler
        self.skills: dict = {}
        self.command_map: dict = {}  # /command → skill
        self.agents: dict = {}      # name → SubAgent

    # ------------------------------------------------------------------
    # Skill registration
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Sub-Agent management (Phase 2)
    # ------------------------------------------------------------------
    def create_agent(self, name: str, system_prompt: str, model: str = None):
        """Create a named sub-agent with its own session."""
        from core.sub_agent import SubAgent
        agent = SubAgent(name, system_prompt, model, self.gemini)
        self.agents[name] = agent
        logger.info(f"Created sub-agent: {name}")
        return agent

    def get_agent(self, name: str):
        return self.agents.get(name)

    # ------------------------------------------------------------------
    # Function Calling tools builder
    # ------------------------------------------------------------------
    def _build_function_declarations(self) -> list:
        """Convert all skills into Gemini Function Calling declarations."""
        declarations = []
        for name, skill in self.skills.items():
            cmd = skill.commands[0].lstrip("/") if skill.commands else name
            declarations.append(
                types.FunctionDeclaration(
                    name=cmd,
                    description=skill.description,
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "args": types.Schema(
                                type="STRING",
                                description="空格分隔的參數字串（可為空）",
                            )
                        },
                    ),
                )
            )
        return declarations

    # ------------------------------------------------------------------
    # NLU routing via Function Calling (Fast Path)
    # ------------------------------------------------------------------
    async def _route_by_function_calling(self, text: str, user_id: int) -> Optional[str]:
        """Use Gemini Function Calling to route to the right skill."""
        tools = [types.Tool(function_declarations=self._build_function_declarations())]

        system_instruction = (
            "你是一個路由器。分析使用者的訊息，判斷是否需要呼叫某個工具。\n"
            "如果需要，就呼叫對應的函式。如果不需要工具，直接回答使用者。\n"
            "請用繁體中文回答。"
        )

        model = self.memory.get_setting(user_id, "preferred_model", None)

        try:
            response = await self.gemini.generate_with_tools(
                prompt=text,
                tools=tools,
                model=model,
                system_instruction=system_instruction,
            )

            # Log usage
            if response.usage_metadata:
                self.memory.log_usage(
                    user_id,
                    model or self.gemini.default_model,
                    response.usage_metadata.prompt_token_count or 0,
                    response.usage_metadata.candidates_token_count or 0,
                )

            # Check if Gemini decided to call a function
            if (response.candidates
                    and response.candidates[0].content
                    and response.candidates[0].content.parts):
                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        fc = part.function_call
                        cmd = f"/{fc.name}"
                        args_str = fc.args.get("args", "") if fc.args else ""
                        args = args_str.split() if args_str else []

                        skill = self.get_skill_for_command(cmd)
                        if skill:
                            logger.info(f"Function Call Routed: '{text}' -> {cmd} {args}")
                            return await skill.handle(cmd, args, user_id)

                # If no function call, return the text response
                if response.text:
                    # Gemini answered directly without tool use — that's valid
                    text_response = response.text
                    self.memory.add_message(user_id, "user", text)
                    self.memory.add_message(user_id, "assistant", text_response[:500])
                    return text_response

        except Exception as e:
            logger.error(f"Function Calling routing failed: {e}")

        return None

    # ------------------------------------------------------------------
    # Main handler: free-text messages
    # ------------------------------------------------------------------
    async def handle_text(self, text: str, user_id: int, cwd: str) -> str:
        """
        Handle free-text messages.
        1. Try Function Calling routing (fast, single API call)
        2. Fall back to direct generation
        """
        # 1. Try Function Calling routing
        routed_result = await self._route_by_function_calling(text, user_id)
        if routed_result is not None:
            return routed_result

        # 2. Direct generation fallback
        logger.info(f"Direct generation for user {user_id}: '{text[:50]}...'")

        # Retrieve semantic context
        semantic_context = self.memory.semantic.search(text)
        context_block = ""
        if semantic_context:
            context_block = f"\n相關背景知識:\n{semantic_context}\n"

        conversation_history = self.memory.get_context(user_id, limit=10)

        system_instruction = (
            "你是一個強大的個人 AI 助手，透過 Telegram 與使用者互動。\n"
            "請用繁體中文回答，語氣友善專業。\n"
            f"{context_block}"
        )

        full_prompt = text
        if conversation_history:
            full_prompt = f"對話歷史:\n{conversation_history}\n\n使用者: {text}"

        model = self.memory.get_setting(user_id, "preferred_model", None)
        response, usage = await self.gemini.generate(
            full_prompt,
            model=model,
            system_instruction=system_instruction,
        )

        # Log usage
        self.memory.log_usage(
            user_id,
            usage.get("model", "unknown"),
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

        # Save to memory
        self.memory.add_message(user_id, "user", text)
        self.memory.add_message(user_id, "assistant", response[:500])

        return response

    # ------------------------------------------------------------------
    # Streaming handler for bot.py
    # ------------------------------------------------------------------
    async def handle_text_stream(self, text: str, user_id: int, cwd: str):
        """
        Handle free-text with streaming output.
        Yields text chunks for the bot to update the message progressively.
        """
        # Retrieve context
        semantic_context = self.memory.semantic.search(text)
        context_block = ""
        if semantic_context:
            context_block = f"\n相關背景知識:\n{semantic_context}\n"

        conversation_history = self.memory.get_context(user_id, limit=10)

        system_instruction = (
            "你是一個強大的個人 AI 助手，透過 Telegram 與使用者互動。\n"
            "請用繁體中文回答，語氣友善專業。\n"
            f"{context_block}"
        )

        full_prompt = text
        if conversation_history:
            full_prompt = f"對話歷史:\n{conversation_history}\n\n使用者: {text}"

        model = self.memory.get_setting(user_id, "preferred_model", None)

        async for chunk in self.gemini.generate_stream(
            full_prompt,
            model=model,
            system_instruction=system_instruction,
        ):
            yield chunk

        # Save to memory after streaming completes
        self.memory.add_message(user_id, "user", text)
