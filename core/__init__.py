"""
Core Engine — Central dispatcher for the Telegram AI Agent.

Uses Google GenAI SDK with native Function Calling for
intelligent routing and multi-step reasoning.
"""
import logging
import config
from typing import Optional, List
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class Engine:
    """Central engine that manages skills, LLM client, and routing."""

    def __init__(self, llm, memory, scheduler=None):
        self.llm = llm
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
        agent = SubAgent(name, system_prompt, model, self.llm)
        self.agents[name] = agent
        logger.info(f"Created sub-agent: {name}")
        return agent

    def get_agent(self, name: str):
        return self.agents.get(name)

    # ------------------------------------------------------------------
    # Memory Distillation (Phase 6)
    # ------------------------------------------------------------------
    async def _distill_history(self, user_id: int, model: str):
        """
        Summarize the current history and prune old messages.
        Triggered when history exceeds a certain threshold.
        """
        history = self.memory.get_context(user_id, limit=30)
        previous_summary = self.memory.get_summary(user_id)
        
        prompt = (
            "你是一個記憶整理專家。以下是使用者與 AI 助理之前的對話歷史與舊的摘要：\n\n"
            f"【舊摘要】：\n{previous_summary if previous_summary else '無'}\n\n"
            f"【最新對話歷史】：\n{history}\n\n"
            "請將以上資訊聚合為一段精簡的「對話背景摘要」。\n"
            "重點包含：使用者是誰、目前正在討論的主題、已經達成的共識或是待辦事項。\n"
            "這段摘要未來會作為 AI 思考時的長期記憶。請用繁體中文回覆，長度控制在 500 字以內。"
        )
        
        try:
            logger.info(f"Distilling history for user {user_id}...")
            messages = [{"role": "user", "content": prompt}]
            response = await self.llm.generate(messages=messages, model=model)
            new_summary = response.choices[0].message.content or ""
            
            if new_summary:
                self.memory.set_summary(user_id, new_summary)
                # Keep only the very last 5 messages as "immediate context"
                self.memory.prune_old_messages(user_id, keep_last_n=5)
                logger.info(f"Successfully distilled memory for user {user_id}.")
        except Exception as e:
            logger.error(f"Memory distillation failed: {e}")

    # ------------------------------------------------------------------
    # Function Calling tools builder
    # ------------------------------------------------------------------
    def _build_tools(self) -> list:
        """Convert all skills into OpenAI JSON Schema tools format."""
        tools = []
        for name, skill in self.skills.items():
            if hasattr(skill, "get_tool_spec"):
                tools.append(skill.get_tool_spec())
        return tools

    # ------------------------------------------------------------------
    # NLU routing via Function Calling (Fast Path)
    # ------------------------------------------------------------------
    async def _route_by_function_calling(self, text: str, user_id: int) -> Optional[str]:
        """Use OpenAI Function Calling to route to the right skill."""
        tools = self._build_tools()
        
        personality = self.memory.get_personality(user_id)
        summary = self.memory.get_summary(user_id)
        summary_block = f"\n【前情提要/對話背景】：\n{summary}\n" if summary else ""

        model_for_distill = self.memory.get_setting(user_id, "preferred_model", None) or config.DEFAULT_MODEL
        
        system_instruction = (
            f"{personality}\n"
            f"{summary_block}"
            "【決策路由器規範】\n"
            "1. 你是一個精準的決策引擎。你的任務是判斷使用者的需求是否需要呼叫工具。\n"
            "2. **嚴禁幻覺**：如果使用者的需求不明確，或者現有工具無法達成，請直接回答使用者，不要嘗試胡亂調用工具。\n"
            "3. **邏輯優先**：在決定調用前，請先在心中確認該工具的參數（如路徑、參數名）是否符合邏輯。\n"
            "4. 如果需要工具，就呼叫對應的函式。如果不需要工具或不確定，直接以文字回覆。\n"
            "5. 請用繁體中文回答。"
        ) if personality else (
            f"{summary_block}"
            "【決策路由器規範】\n"
            "1. 你是一個精準的決策引擎。判斷是否需要呼叫工具。\n"
            "2. 如果不確定使用者意圖，請不要冒險調用工具，改為詢問使用者詳情。\n"
            "3. 嚴禁為不存在的檔案或路徑生成虛假參數。\n"
            "4. 如果需要工具，就呼叫對應的函式。如果不需要工具，直接回答使用者。\n"
            "5. 請用繁體中文回答。"
        )

        model = self.memory.get_setting(user_id, "preferred_model", None) or config.DEFAULT_MODEL
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": text}
        ]

        try:
            response = await self.llm.generate(
                messages=messages,
                tools=tools,
                model=model,
            )

            message = response.choices[0].message
            
            # Log usage if available
            if hasattr(response, 'usage') and response.usage:
                self.memory.log_usage(
                    user_id,
                    model,
                    response.usage.prompt_tokens or 0,
                    response.usage.completion_tokens or 0,
                )

            # Check if model decided to call a function
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.type == "function":
                        fc = tool_call.function
                        cmd = f"/{fc.name}"
                        
                        # Parse JSON arguments
                        args_dict = {}
                        if fc.arguments:
                            try:
                                args_dict = json.loads(fc.arguments)
                            except json.JSONDecodeError:
                                pass
                                
                        args_str = args_dict.get("args", "")
                        args = args_str.split() if args_str else []

                        skill = self.get_skill_for_command(cmd)
                        if skill:
                            logger.info(f"Function Call Routed: '{text}' -> {cmd} {args}")
                            
                            # Add user message before skill execution
                            self.memory.add_message(user_id, "user", text)
                            
                            result = await skill.handle(cmd, args, user_id)
                            
                            # Add assistant message after skill execution
                            self.memory.add_message(user_id, "assistant", result[:500])
                            
                            # Check for distillation after skill
                            if self.memory.get_message_count(user_id) > 20:
                                await self._distill_history(user_id, model_for_distill)
                                
                            return result

            # If no function call, return the text response
            if message.content:
                text_response = message.content
                self.memory.add_message(user_id, "user", text)
                self.memory.add_message(user_id, "assistant", text_response[:500])
                return text_response

        except Exception as e:
            logger.error(f"Function Calling routing failed: {e}")

        return None

    # ------------------------------------------------------------------
    # Shared Helper: Build Chat Messages
    # ------------------------------------------------------------------
    def _build_chat_messages(self, text: str, user_id: int) -> list[dict[str, str]]:
        """
        Builds the standard message payload (system and user roles) 
        including memory, semantics, and personality context.
        """
        semantic_context = self.memory.semantic.search(text)
        context_block = ""
        if semantic_context:
            context_block = f"\n相關背景知識:\n{semantic_context}\n"

        conversation_history = self.memory.get_context(user_id, limit=10)

        personality = self.memory.get_personality(user_id)
        summary = self.memory.get_summary(user_id)
        summary_block = f"\n【前情提要/對話背景】：\n{summary}\n" if summary else ""

        system_instruction = (
            f"{personality}\n"
            f"{summary_block}"
            "【行為準則】\n"
            "1. 你是一個強大的個人 AI 助手。你的回答必須基於事實。\n"
            "2. **誠實原則**：如果你不知道答案，或者缺乏足夠的上下文來回答，請直接承認，不要編造事實（避免幻覺）。\n"
            "3. **安全執行**：不要執行可能損害系統安全的危險建議。\n"
            "4. **精簡有效**：回答應直擊重點，應對及時。\n"
            "請用繁體中文回答，語氣友善專業。\n"
            f"{context_block}"
        ) if personality else (
            f"{summary_block}"
            "【行為準則】\n"
            "1. 你是一個強大的個人 AI 助手。請用繁體中文回答，語氣友善專業。\n"
            "2. **避免幻覺**：若不確定事實，請誠實告知使用者「我不知道」或「我需要更多資訊」。\n"
            "3. 確保你的回答不包含虛假的代碼示例或不存在的 API 調用。\n"
            f"{context_block}"
        )

        full_prompt = text
        if conversation_history:
            full_prompt = f"對話歷史:\n{conversation_history}\n\n使用者: {text}"

        return [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": full_prompt}
        ]

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

        messages = self._build_chat_messages(text, user_id)
        model = self.memory.get_setting(user_id, "preferred_model", None) or config.DEFAULT_MODEL
        
        response = await self.llm.generate(
            messages=messages,
            model=model,
        )
        
        message_content = response.choices[0].message.content or ""

        # Log usage
        if hasattr(response, 'usage') and response.usage:
            self.memory.log_usage(
                user_id,
                model,
                response.usage.prompt_tokens or 0,
                response.usage.completion_tokens or 0,
            )

        # Save to memory
        self.memory.add_message(user_id, "user", text)
        self.memory.add_message(user_id, "assistant", message_content[:500])

        # Phase 6: Check for distillation
        if self.memory.get_message_count(user_id) > 20:
             await self._distill_history(user_id, model)

        return message_content

    # ------------------------------------------------------------------
    # Streaming handler for bot.py
    # ------------------------------------------------------------------
    async def handle_text_stream(self, text: str, user_id: int, cwd: str):
        """
        Handle free-text with streaming output.
        Yields text chunks for the bot to update the message progressively.
        """
        messages = self._build_chat_messages(text, user_id)
        model = self.memory.get_setting(user_id, "preferred_model", None) or config.DEFAULT_MODEL

        async for chunk in self.llm.stream(
            messages=messages,
            model=model,
        ):
            yield chunk

        # Save to memory after streaming completes
        self.memory.add_message(user_id, "user", text)
        
        # Phase 6: Check for distillation
        if self.memory.get_message_count(user_id) > 20:
             await self._distill_history(user_id, model)
