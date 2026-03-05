"""
Dev Agent Skill — Direct AI development via Gemini SDK.
This is the handler for explicit /dev commands.
"""
from .base_skill import BaseSkill


class DevAgentSkill(BaseSkill):
    name = "dev_agent"
    description = "AI 開發助手 — 透過 Gemini 進行程式開發、除錯、分析"
    commands = ["/dev"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            return (
                "💻 **Dev Agent**\n\n"
                "直接發送文字訊息即可與 Gemini 對話。\n"
                "或使用 `/dev <指令>` 明確指定開發任務。\n\n"
                "😊 範例:\n"
                "• `/dev 分析 server.py 有什麼可以優化`\n"
                "• `/dev 幫我寫一個 Flask REST API`\n"
                "• 直接打字: `幫我看看這段 code 有什麼問題`"
            )

        prompt = " ".join(args)
        model = self.engine.memory.get_setting(user_id, "preferred_model", None)

        system_instruction = (
            "你是一個專業的軟體工程師 AI 助手。\n"
            "請用繁體中文回答，提供精確且實用的程式碼建議。\n"
            "如果提供程式碼，請使用 markdown code block 格式。"
        )

        response, usage = await self.engine.gemini.generate(
            prompt,
            model=model,
            system_instruction=system_instruction,
        )

        # Log usage
        self.engine.memory.log_usage(
            user_id,
            usage.get("model", "unknown"),
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

        return response
