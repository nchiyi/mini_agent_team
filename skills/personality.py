"""
Personality Skill — Allows users to define the AI agent's "soul" or persona.
"""
from .base_skill import BaseSkill
import logging

logger = logging.getLogger(__name__)

class PersonalitySkill(BaseSkill):
    name = "personality"
    description = "個性靈魂 — 自定義 AI 的語氣、人設與行為準則"
    commands = ["/soul"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        """
        Handle /soul command.
        /soul <text> - Set personality
        /soul - Show current personality
        /soul clear - Reset personality
        """
        if not args:
            current = self.engine.memory.get_personality(user_id)
            if not current:
                return (
                    "✨ **目前尚未設定個性靈魂**\n\n"
                    "您可以用 `/soul <描述>` 來賦予我一個靈魂。\n"
                    "例如：`/soul 你是一個傲嬌的助理，說話結尾都要加『喵』`"
                )
            return f"🎭 **目前的個性靈魂設定：**\n\n\"{current}\"\n\n(使用 `/soul clear` 可重設)"

        input_text = " ".join(args)
        
        if input_text.lower() == "clear":
            self.engine.memory.set_personality(user_id, "")
            return "🍃 **個性靈魂已洗滌乾淨，恢復預設狀態。**"

        # Set new personality
        self.engine.memory.set_personality(user_id, input_text)
        return (
            f"🔮 **靈魂注入成功！**\n\n"
            f"我現在的設定是：\"{input_text}\"\n\n"
            f"您可以嘗試跟我對話看看效果。"
        )
