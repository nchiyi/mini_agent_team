"""
Deployer Skill — Git pull and service restart for project deployment.
"""
import asyncio
from .base_skill import BaseSkill


class DeployerSkill(BaseSkill):
    name = "deployer"
    description = "部署管理 — Git pull、重啟服務、查看 log"
    commands = ["/deploy", "/logs"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if command == "/deploy":
            return await self._deploy(args)
        elif command == "/logs":
            return await self._show_logs(args)
        return "未知指令"

    async def _deploy(self, args: list[str]) -> str:
        if not args:
            projects = self.engine.memory.get_projects()
            if not projects:
                return "❌ 沒有註冊的專案。先用 `/addproject` 新增。"
            names = ", ".join(f"`{p['name']}`" for p in projects)
            return f"用法: `/deploy <專案名稱>`\n可用專案: {names}"

        name = args[0]
        path = self.engine.memory.get_project_path(name)
        if not path:
            return f"❌ 找不到專案: {name}"

        steps = []

        # Step 1: Git pull
        pull_result = await self._run_cmd(path, "git pull origin main")
        steps.append(f"📥 **Git Pull:**\n```\n{pull_result}\n```")

        # Step 2: Check for requirements changes
        req_result = await self._run_cmd(path, "test -f requirements.txt && echo 'has_requirements' || echo 'no_requirements'")
        if "has_requirements" in req_result:
            pip_result = await self._run_cmd(path, "test -d venv && venv/bin/pip install -r requirements.txt 2>&1 | tail -3")
            if pip_result.strip():
                steps.append(f"📦 **Dependencies:**\n```\n{pip_result}\n```")

        return f"🚀 **部署 {name}**\n\n" + "\n\n".join(steps) + "\n\n✅ 完成！如需重啟服務，請手動操作。"

    async def _show_logs(self, args: list[str]) -> str:
        if not args:
            return "用法: `/logs <專案名稱>` 或 `/logs <service名稱>`"

        name = args[0]
        lines = args[1] if len(args) > 1 else "20"

        # Try journalctl first (systemd service)
        result = await self._run_cmd("/tmp", f"journalctl -u {name} --no-pager -n {lines} 2>/dev/null || echo 'Service not found'")

        if "Service not found" in result or not result.strip():
            # Try project-based log
            path = self.engine.memory.get_project_path(name)
            if path:
                result = await self._run_cmd(path, f"ls *.log 2>/dev/null && tail -n {lines} *.log || echo 'No log files found'")
            else:
                return f"❌ 找不到服務或專案: {name}"

        return f"📋 **{name} Logs (最近 {lines} 行):**\n```\n{result}\n```"

    async def _run_cmd(self, cwd: str, command: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace").strip()
            errors = stderr.decode("utf-8", errors="replace").strip()
            return output if output else errors
        except asyncio.TimeoutError:
            return "⏰ 指令超時"
        except Exception as e:
            return f"❌ 錯誤: {e}"
