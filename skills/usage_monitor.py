"""
Usage Monitor Skill — Monitor Token usage and costs via Gemini CLI.
"""
import asyncio
import logging
from .base_skill import BaseSkill

logger = logging.getLogger(__name__)

class UsageMonitorSkill(BaseSkill):
    name = "usage_monitor"
    description = "用量監控 — 查看目前 Gemini API 的 Token 消耗與預估成本"
    commands = ["/usage"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        """Call 'gemini usage' and return the result."""
        # Note: We run this in /tmp to avoid any localized session issues if they exist
        cwd = "/tmp"
        
        try:
            # We use the same environment as the bot (Linux/Ubuntu expected)
            proc = await asyncio.create_subprocess_exec(
                "gemini", "usage",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            
            output = stdout.decode("utf-8", errors="replace").strip()
            error = stderr.decode("utf-8", errors="replace").strip()
            
            if not output and error:
                return f"❌ 查詢失敗:\n```\n{error}\n```"
            
            if not output:
                return "⚠️ 無法取得用量數據（CLI 未回傳內容）。"

            return f"📊 **Gemini API 使用量統計**\n\n```\n{output}\n```\n\n💡 提示：用量數據由 Gemini CLI 提供，包含此 Bot 與其他終端機操作的總和。"

        except FileNotFoundError:
            return "❌ 系統找不到 `gemini` 指令，請確認 Gemini CLI 已正確安裝。"
        except asyncio.TimeoutError:
            return "⏰ 查詢超時，請稍後再試。"
        except Exception as e:
            logger.error(f"Usage monitor error: {e}")
            return f"❌ 發生非預期錯誤: {e}"
