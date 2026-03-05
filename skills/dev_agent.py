"""
Dev Agent Skill — Direct AI development via Gemini CLI.
This is the default handler for free-text messages.
"""
from .base_skill import BaseSkill


class DevAgentSkill(BaseSkill):
    name = "dev_agent"
    description = "AI 開發助手 — 透過 Gemini CLI 進行程式開發、除錯、分析"
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
        cwd = self.engine.memory.get_setting(user_id, "cwd", "")
        if not cwd:
            cwd = self.engine.memory.get_setting(user_id, "default_cwd", "/tmp")

        return await self.engine.gemini.execute(prompt, cwd)
