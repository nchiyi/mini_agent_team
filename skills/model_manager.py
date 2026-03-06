"""
Model Manager Skill — Switch between different Gemini models.
Now with dynamic model listing from Google API.
"""
from .base_skill import BaseSkill
import config


class ModelManagerSkill(BaseSkill):
    name = "model_manager"
    description = "模型管理 — 切換 AI 模型、查看可用模型清單"
    commands = ["/model"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            current = self.engine.memory.get_setting(
                user_id, "preferred_model",
                ""
            )
            default = "llama3.1 (預設)"
            display_current = current if current else default
            return (
                f"🤖 **模型管理**\n\n"
                f"目前設定: `{display_current}`\n\n"
                f"用法:\n"
                f"• `/model list` — 查看 Ollama 所有可用模型\n"
                f"• `/model <模型名稱>` — 切換模型\n"
                f"• `/model reset` — 恢復預設\n\n"
                f"可用範例:\n"
                f"• `llama3.1`\n"
                f"• `qwen2.5`\n"
                f"• `mistral`"
            )

        action = args[0].lower()

        if action == "list":
            return await self._list_models()
        elif action == "reset":
            self.engine.memory.set_setting(user_id, "preferred_model", "")
            return f"✅ 已恢復預設模型"
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
        """Dynamically list all available models from Ollama API."""
        try:
            # We use the custom list_models on OllamaClient
            models = await self.engine.llm.list_models()
            
            allowed = [m.strip() for m in config.ALLOWED_MODELS.split(",") if m.strip()]
            
            # Filter based on ALLOWED_MODELS
            if allowed:
                models["local"] = [m for m in models["local"] if m in allowed]
                models["cloud"] = [m for m in models["cloud"] if f"cloud:{m}" in allowed]
            
            if not models["local"] and not models["cloud"]:
                return "❌ 找不到可用的模型，請確定您已安裝或設定正確的 API Key。"

            lines = ["📋 **目前可用的 Ollama 模型:**\n"]
            
            if models["local"]:
                lines.append("🏠 **[本地 Local]**")
                for m in models["local"][:15]:  # Limit display
                    lines.append(f"• `{m}`")
                lines.append("")

            if models["cloud"]:
                lines.append("☁️ **[雲端 Cloud]**")
                for m in models["cloud"][:15]:  # Limit display
                    lines.append(f"• `cloud:{m}`")
                lines.append("")

            lines.append(f"使用 `/model <名稱>` 來切換模型")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 查詢模型時發生錯誤: {e}"

    async def _validate_model(self, model_name: str) -> bool:
        """Check if an Ollama model name is valid and allowed."""
        try:
            allowed = [m.strip() for m in config.ALLOWED_MODELS.split(",") if m.strip()]
            if allowed and model_name not in allowed:
                return False

            models = await self.engine.llm.list_models()
            if model_name.startswith("cloud:"):
                return model_name[6:] in models["cloud"]
            return model_name in models["local"]
        except Exception:
            return True  # If we can't validate, allow it anyway
