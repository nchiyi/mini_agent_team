"""
System Monitor Skill — Check CPU, memory, disk usage.
"""
import asyncio
from .base_skill import BaseSkill


class SystemMonitorSkill(BaseSkill):
    name = "system_monitor"
    description = "系統監控 — 查看伺服器 CPU、記憶體與磁碟使用量"
    commands = ["/sys"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        info = await self._get_system_info()
        return info

    async def _get_system_info(self) -> str:
        """Gather system info using standard Linux tools."""
        try:
            # CPU & Memory
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c",
                "echo '=CPU='; top -bn1 | head -5; "
                "echo '=MEM='; free -h; "
                "echo '=DISK='; df -h / /home 2>/dev/null; "
                "echo '=UPTIME='; uptime",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            raw = stdout.decode("utf-8", errors="replace")

            # Parse sections
            lines = raw.strip().split("\n")
            cpu_lines = []
            mem_lines = []
            disk_lines = []
            uptime_line = ""
            section = ""

            for line in lines:
                if line.startswith("=CPU="):
                    section = "cpu"
                    continue
                elif line.startswith("=MEM="):
                    section = "mem"
                    continue
                elif line.startswith("=DISK="):
                    section = "disk"
                    continue
                elif line.startswith("=UPTIME="):
                    section = "uptime"
                    continue

                if section == "cpu":
                    cpu_lines.append(line)
                elif section == "mem":
                    mem_lines.append(line)
                elif section == "disk":
                    disk_lines.append(line)
                elif section == "uptime":
                    uptime_line = line.strip()

            return (
                f"🖥️ **系統狀態**\n\n"
                f"⏱ **Uptime:** {uptime_line}\n\n"
                f"🧠 **記憶體:**\n```\n" + "\n".join(mem_lines) + "\n```\n\n"
                f"💾 **磁碟:**\n```\n" + "\n".join(disk_lines) + "\n```"
            )

        except Exception as e:
            return f"❌ 無法取得系統資訊: {e}"
