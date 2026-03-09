"""
Engine — core brain of the AI agent.
"""
import logging
import json
import re
from typing import Optional, List
from datetime import datetime, timedelta

import config
from core.memory import Memory
from core.ollama_client import OllamaClient

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
        previous_facts = self.memory.get_user_facts(user_id)
        previous_context = self.memory.get_session_context(user_id)
        
        # Migrate old summary if it exists and new keys are empty
        old_summary = self.memory.get_summary(user_id)
        if old_summary and not previous_facts and not previous_context:
            previous_context = old_summary
        
        prompt = (
            "你是一個記憶整理專家。以下是使用者與 AI 助理之前的對話歷史與舊的記憶：\n\n"
            f"【舊的使用者長期事實】：\n{previous_facts if previous_facts else '無'}\n\n"
            f"【舊的目前任務摘要】：\n{previous_context if previous_context else '無'}\n\n"
            f"【最新對話歷史】：\n{history}\n\n"
            "請將以上資訊進行這**兩個獨立的區塊**的聚合與更新：\n"
            "1. 【使用者長期事實】：整理出關於使用者不變的事實（如：職業、喜好、習慣、個人細節）。"
            "如果沒有新發現，請保留舊事實。如果使用者明確說了與舊事實矛盾的新資訊（例如換了工作），請更新為最新版本。\n"
            "2. 【目前任務摘要】：整理出目前兩人正在討論的主題、待辦事項或是前情提要。如果話題已經切換，請專注於最新的任務。\n\n"
            "請嚴格使用以下 XML 格式回覆，不要輸出其他廢話：\n"
            "<facts>\n長期事實內容寫這裡...\n</facts>\n"
            "<session>\n任務摘要寫這裡...\n</session>"
        )
        
        try:
            logger.info(f"Distilling history for user {user_id}...")
            messages = [{"role": "user", "content": prompt}]
            response = await self.llm.generate(messages=messages, model=model)
            new_summary = response.choices[0].message.content or ""
            
            if new_summary:
                facts_match = re.search(r"<facts>(.*?)</facts>", new_summary, re.DOTALL)
                session_match = re.search(r"<session>(.*?)</session>", new_summary, re.DOTALL)
                
                if facts_match:
                    self.memory.set_user_facts(user_id, facts_match.group(1).strip())
                if session_match:
                    self.memory.set_session_context(user_id, session_match.group(1).strip())

                # Fallback if the LLM didn't format it right
                if not facts_match and not session_match:
                    self.memory.set_session_context(user_id, new_summary)
                    
                # Keep only the very last 5 messages as "immediate context"
                self.memory.prune_old_messages(user_id, keep_last_n=5)
                # Record the timestamp for cooldown guard
                self.memory.set_setting(user_id, "last_distill_ts", datetime.now().isoformat())
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
        
        user_facts = self.memory.get_user_facts(user_id)
        session_context = self.memory.get_session_context(user_id)
        if not user_facts and not session_context:
            session_context = self.memory.get_summary(user_id)

        facts_block = f"\n【關於使用者的長期事實】：\n{user_facts}\n" if user_facts else ""
        session_block = f"\n【目前對話前情提要】：\n{session_context}\n" if session_context else ""

        model_for_distill = self.memory.get_setting(user_id, "preferred_model", None) or config.DEFAULT_MODEL
        
        system_instruction = (
            f"{personality}\n"
            f"{facts_block}{session_block}"
            "【決策路由器規範】\n"
            "1. 你是一個精準的決策引擎。你的任務是判斷使用者的需求是否需要呼叫工具。\n"
            "2. **嚴禁幻覺**：如果使用者的需求不明確，或者現有工具無法達成，請直接回答使用者，不要嘗試胡亂調用工具。\n"
            "3. **邏輯優先**：在決定調用前，請先在心中確認該工具的參數（如路徑、參數名）是否符合邏輯。\n"
            "4. 如果需要工具，就呼叫對應的函式。如果不需要工具或不確定，直接以文字回覆。\n"
            "5. 請用繁體中文回答。"
        ) if personality else (
            f"{facts_block}{session_block}"
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
                            self.memory.add_message(user_id, "assistant", result[:1000])
                            
                            # Check for distillation after skill (with cooldown)
                            if self._should_distill(user_id):
                                await self._distill_history(user_id, model_for_distill)
                                
                            return result

            # If no function call, return the text response
            if message.content:
                text_response = message.content
                self.memory.add_message(user_id, "user", text)
                self.memory.add_message(user_id, "assistant", text_response[:1000])
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
        
        user_facts = self.memory.get_user_facts(user_id)
        session_context = self.memory.get_session_context(user_id)
        if not user_facts and not session_context:
            session_context = self.memory.get_summary(user_id)

        facts_block = f"\n【關於使用者的長期事實】：\n{user_facts}\n" if user_facts else ""
        session_block = f"\n【目前對話前情提要】：\n{session_context}\n" if session_context else ""

        system_instruction = (
            f"{personality}\n"
            f"{facts_block}{session_block}"
            "【行為準則】\n"
            "1. 你是一個強大的個人 AI 助手。你的回答必須基於事實。\n"
            "2. **誠實原則**：如果你不知道答案，或者缺乏足夠的上下文來回答，請直接承認，不要編造事實（避免幻覺）。\n"
            "3. **安全執行**：不要執行可能損害系統安全的危險建議。\n"
            "4. **精簡有效**：回答應直擊重點，應對及時。\n"
            "請用繁體中文回答，語氣友善專業。\n"
            f"{context_block}"
        ) if personality else (
            f"{facts_block}{session_block}"
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
        self.memory.add_message(user_id, "assistant", message_content[:1000])

        # Check for distillation (with cooldown)
        if self._should_distill(user_id):
             await self._distill_history(user_id, model)

        return message_content

    # ------------------------------------------------------------------
    # Streaming handler for bot.py
    # ------------------------------------------------------------------
    async def handle_text_stream(self, text: str, user_id: int, cwd: str):
        """
        Handle free-text with streaming output.
        Yields text chunks for the bot to update the message progressively.
        Collects the full response and saves it to memory after streaming.
        """
        messages = self._build_chat_messages(text, user_id)
        model = self.memory.get_setting(user_id, "preferred_model", None) or config.DEFAULT_MODEL

        # Collect the full response while yielding chunks
        full_response_parts: list[str] = []
        async for chunk in self.llm.stream(
            messages=messages,
            model=model,
        ):
            full_response_parts.append(chunk)
            yield chunk

        # Save BOTH user message AND assistant reply to memory
        full_response = "".join(full_response_parts)
        self.memory.add_message(user_id, "user", text)
        self.memory.add_message(user_id, "assistant", full_response[:1000])
        
        # Check for distillation (with cooldown)
        if self._should_distill(user_id):
             await self._distill_history(user_id, model)

    # ------------------------------------------------------------------
    # Distillation Cooldown Guard
    # ------------------------------------------------------------------
    _DISTILL_COOLDOWN = timedelta(minutes=30)

    def _should_distill(self, user_id: int) -> bool:
        """
        Check if distillation should run: message count > 20 AND at least
        30 minutes have passed since the last distillation.
        """
        if self.memory.get_message_count(user_id) <= 20:
            return False
        last_distill = self.memory.get_setting(user_id, "last_distill_ts", "")
        if last_distill:
            try:
                last_dt = datetime.fromisoformat(last_distill)
                if datetime.now() - last_dt < self._DISTILL_COOLDOWN:
                    return False
            except ValueError:
                pass  # Corrupted timestamp, allow distillation
        return True
