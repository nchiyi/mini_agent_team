"""
Model Manager Skill — Switch between different Gemini models.
Now with dynamic model listing from Google API.
"""
from .base_skill import BaseSkill


class ModelManagerSkill(BaseSkill):
    name = "model_manager"
    description = "模型管理 — 切換 Gemini 模型、查看可用模型清單"
    commands = ["/model"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            current = self.engine.memory.get_setting(
                user_id, "preferred_model",
                f"{self.engine.gemini.default_model} (預設)"
            )
            return (
                f"🤖 **模型管理**\n\n"
                f"目前設定: `{current}`\n\n"
                f"用法:\n"
                f"• `/model list` — 查看所有可用模型\n"
                f"• `/model <模型名稱>` — 切換模型\n"
                f"• `/model reset` — 恢復預設\n\n"
                f"常用模型:\n"
                f"• `gemini-2.0-flash` (速度快、便宜)\n"
                f"• `gemini-2.5-pro` (強大推理)\n"
                f"• `gemini-2.5-flash` (平衡)"
            )

        action = args[0].lower()

        if action == "list":
            return await self._list_models()
        elif action == "reset":
            self.engine.memory.set_setting(user_id, "preferred_model", "")
            default = self.engine.gemini.default_model
            return f"✅ 已恢復預設模型: `{default}`"
        else:
            new_model = args[0]
            # Validate model exists
            valid = await self._validate_model(new_model)
            if not valid:
                return (
                    f"⚠️ 模型 `{new_model}` 可能無效。\n"
                    f"仍然為您設定，但如果出錯請使用 `/model list` 查看可用模型。"
                )

            self.engine.memory.set_setting(user_id, "preferred_model", new_model)
            return f"✅ 已將模型切換為: `{new_model}`\n接下來的對話將使用此模型。"

    async def _list_models(self) -> str:
        """Dynamically list all available models from Google API."""
        try:
            models = self.engine.gemini.list_models()
            if not models:
                return "❌ 無法取得模型清單"

            # Filter for gemini models only
            gemini_models = [m for m in models if "gemini" in m["name"].lower()]

            if not gemini_models:
                return "❌ 找不到可用的 Gemini 模型"

            lines = ["📋 **目前可用的 Gemini 模型:**\n"]
            for m in gemini_models[:15]:  # Limit display
                name = m["name"].replace("models/", "")
                display = m.get("display_name", name)
                lines.append(f"• `{name}`  —  {display}")

            lines.append(f"\n\n使用 `/model <名稱>` 來切換模型")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 查詢模型時發生錯誤: {e}"

    async def _validate_model(self, model_name: str) -> bool:
        """Check if a model name is valid."""
        try:
            models = self.engine.gemini.list_models()
            names = [m["name"].replace("models/", "") for m in models]
            return model_name in names
        except Exception:
            return True  # If we can't validate, allow it anyway
