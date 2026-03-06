"""
Skill Installer — Dynamically download and install skills from a URL.
"""
import asyncio
import os
import aiohttp
import importlib
from urllib.parse import urlparse
from .base_skill import BaseSkill
from skills import discover_skills

# Trusted domains for skill downloads
TRUSTED_DOMAINS = [
    "raw.githubusercontent.com",
    "gist.githubusercontent.com",
    "gitlab.com",
]


class SkillInstallerSkill(BaseSkill):
    name = "skill_installer"
    description = "動態安裝 Skill — 透過網址下載並即時載入新功能"
    commands = ["/install"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not args:
            return (
                "🔧 **Skill Installer**\n\n"
                "用法: `/install <Raw_Script_URL>`\n"
                "範例: `/install https://raw.githubusercontent.com/.../my_skill.py`\n\n"
                "⚠️ 請確保來源可信，安裝後會立即生效。"
            )

        url = args[0]
        if not url.startswith("http"):
            return "❌ 請提供有效的 HTTP/HTTPS 網址。"

        # Security: Check trusted domain
        parsed = urlparse(url)
        if parsed.hostname not in TRUSTED_DOMAINS:
            allowed = ", ".join(f"`{d}`" for d in TRUSTED_DOMAINS)
            return (
                f"🚫 **安全限制：**不信任的來源域名 `{parsed.hostname}`。\n\n"
                f"僅允許以下受信任來源：\n{allowed}\n\n"
                f"如需新增受信任域名，請修改 `skill_installer.py` 中的 `TRUSTED_DOMAINS`。"
            )

        # Generate filename from URL
        filename = url.split("/")[-1]
        if not filename.endswith(".py"):
            filename += ".py"
            
        # Prevent overwriting core files
        protected_files = ["__init__.py", "base_skill.py"]
        if filename in protected_files:
            return f"❌ 無法覆蓋受保護的檔案: {filename}"

        skills_dir = os.path.dirname(__file__)
        filepath = os.path.join(skills_dir, filename)

        try:
            # Download the file
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return f"❌ 下載失敗: HTTP {response.status}"
                    content = await response.text()

            # Basic validation
            if "class " not in content or "BaseSkill" not in content:
                return "❌ 檔案格式錯誤：必須包含繼承自 BaseSkill 的類別。"

            # Save the file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

            # Hot reload
            return self._reload_skills(filename)

        except Exception as e:
            return f"❌ 安裝過程中發生錯誤: {e}"

    def _reload_skills(self, filename: str) -> str:
        """Register the new skill without restarting the bot."""
        module_name = filename[:-3]
        try:
            # Import the new module
            module = importlib.import_module(f"skills.{module_name}")
            importlib.reload(module)  # Force reload if it already existed

            # Find and register the new skill
            new_skills_added = []
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseSkill)
                    and attr is not BaseSkill
                ):
                    skill = attr()
                    self.engine.register_skill(skill)
                    new_skills_added.append(skill.name)

            if new_skills_added:
                names = ", ".join(new_skills_added)
                return f"✅ 成功下載並載入 Skill: **{names}**"
            else:
                return "⚠️ 下載成功，但找不到繼承 BaseSkill 的類別。"

        except Exception as e:
            # Clean up the bad file
            os.remove(os.path.join(os.path.dirname(__file__), filename))
            return f"❌ 載入失敗 (檔案已刪除): {e}"
