"""
Model Manager Skill — Switch between different Gemini models.
"""
from .base_skill import BaseSkill

class ModelManagerSkill(BaseSkill):
    name = "model_manager"
    description = "模型管理 — 切換 Gemini 模型 (如 1.5-pro, 2.0-flash)"
    commands = ["/model"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            current = self.engine.memory.get_setting(user_id, "preferred_model", "gemini-2.0-flash (預設)")
            return (
                f"🤖 **模型管理**\n\n"
                f"目前設定: `{current}`\n\n"
                f"可用選項:\n"
                f"• `/model gemini-2.0-flash` (速度快、便宜)\n"
                f"• `/model gemini-1.5-pro` (強大推理、較貴)\n"
                f"• `/model gemini-3.1-flash-lite` (極速、極廉價)\n\n"
                f"用法: `/model <模型名稱>`"
            )

        new_model = args[0]
        # Basic validation (optional)
        self.engine.memory.set_setting(user_id, "preferred_model", new_model)
        
        return f"✅ 已將您的偏好模型切換為: `{new_model}`\n接下來的對話將使用此模型。"
