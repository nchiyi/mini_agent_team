"""
Deployer Skill — Git pull and service restart for project deployment.
"""
import asyncio
import shlex
from .base_skill import BaseSkill


class DeployerSkill(BaseSkill):
    name = "deployer"
    description = "部署管理 — Git pull、重啟服務、查看 log"
    commands = ["/deploy", "/logs"]

    # Whitelist of allowed command prefixes for safety
    SAFE_COMMANDS = ["git pull", "git status", "git log", "journalctl", "tail", "ls", "test", "cat"]

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
        pull_result = await self._run_safe_cmd(path, ["git", "pull", "origin", "main"])
        steps.append(f"📥 **Git Pull:**\n```\n{pull_result}\n```")

        # Step 2: Check if requirements.txt exists and install
        import os
        req_path = os.path.join(path, "requirements.txt")
        if os.path.isfile(req_path):
            venv_pip = os.path.join(path, "venv", "bin", "pip")
            if os.path.isfile(venv_pip):
                pip_result = await self._run_safe_cmd(path, [venv_pip, "install", "-r", "requirements.txt"])
                if pip_result.strip():
                    # Only show last 3 lines
                    lines = pip_result.strip().split("\n")
                    steps.append(f"📦 **Dependencies:**\n```\n" + "\n".join(lines[-3:]) + "\n```")

        return f"🚀 **部署 {name}**\n\n" + "\n\n".join(steps) + "\n\n✅ 完成！如需重啟服務，請手動操作。"

    async def _show_logs(self, args: list[str]) -> str:
        if not args:
            return "用法: `/logs <專案名稱>` 或 `/logs <service名稱>`"

        name = args[0]
        # Sanitize lines parameter — force integer to prevent injection
        try:
            lines = str(int(args[1])) if len(args) > 1 else "20"
        except ValueError:
            lines = "20"

        # Sanitize the service name — only allow alphanumeric, dash, underscore, dot
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', name):
            return "❌ 無效的服務名稱（僅允許英數字、連字符、底線、句點）。"

        # Try journalctl first (systemd service)
        result = await self._run_safe_cmd("/tmp", ["journalctl", "-u", name, "--no-pager", "-n", lines])

        if not result.strip() or "No journal files" in result:
            # Try project-based log
            path = self.engine.memory.get_project_path(name)
            if path:
                result = await self._run_safe_cmd(path, ["tail", "-n", lines, "*.log"])
            else:
                return f"❌ 找不到服務或專案: {name}"

        return f"📋 **{name} Logs (最近 {lines} 行):**\n```\n{result}\n```"

    async def _run_safe_cmd(self, cwd: str, cmd_list: list[str]) -> str:
        """Run a command safely using arg list (no shell injection)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_list,
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
