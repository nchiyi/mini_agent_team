"""
System Monitor Skill — Check CPU, memory, disk usage.
Cross-platform support using psutil.
"""
import logging
from .base_skill import BaseSkill

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class SystemMonitorSkill(BaseSkill):
    name = "system_monitor"
    description = "伺服器系統監控。當使用者詢問伺服器狀態、CPU 使用率、記憶體用量、磁碟空間、系統效能、機器健康狀況、或說「機器好慢」「伺服器正常嗎」時使用。"
    commands = ["/sys"]

    def get_tool_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "sys",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "args": {
                            "type": "string",
                            "description": "查詢類型（可留空表示查看全部系統狀態）"
                        }
                    },
                    "required": []
                }
            }
        }

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if not PSUTIL_AVAILABLE:
            return (
                "❌ 系統監控功能未啟動（缺少 `psutil`）。\n"
                "請在伺服器端執行 `pip install psutil`。"
            )
        return self._get_system_info()

    def _get_system_info(self) -> str:
        """Gather system info using psutil (cross-platform)."""
        try:
            import datetime

            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()

            # Memory
            mem = psutil.virtual_memory()
            mem_total_gb = mem.total / (1024 ** 3)
            mem_used_gb = mem.used / (1024 ** 3)
            mem_percent = mem.percent

            # Disk
            disk = psutil.disk_usage('/')
            disk_total_gb = disk.total / (1024 ** 3)
            disk_used_gb = disk.used / (1024 ** 3)
            disk_percent = disk.percent

            # Uptime
            boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.datetime.now() - boot_time
            uptime_str = str(uptime).split('.')[0]  # Remove microseconds

            # Progress bars
            def bar(pct: float) -> str:
                filled = int(pct / 10)
                return "█" * filled + "░" * (10 - filled)

            return (
                f"🖥️ **系統狀態**\n\n"
                f"⏱ **Uptime:** {uptime_str}\n\n"
                f"⚡ **CPU:** {cpu_percent}% ({cpu_count} cores)\n"
                f"  [{bar(cpu_percent)}]\n\n"
                f"🧠 **記憶體:** {mem_used_gb:.1f} / {mem_total_gb:.1f} GB ({mem_percent}%)\n"
                f"  [{bar(mem_percent)}]\n\n"
                f"💾 **磁碟 (/):** {disk_used_gb:.1f} / {disk_total_gb:.1f} GB ({disk_percent}%)\n"
                f"  [{bar(disk_percent)}]"
            )

        except Exception as e:
            logger.error(f"System monitor error: {e}")
            return f"❌ 無法取得系統資訊: {e}"
