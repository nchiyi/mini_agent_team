"""
Project Tracker Skill — Git-based project monitoring.
"""
import asyncio
import os
from .base_skill import BaseSkill


class ProjectTrackerSkill(BaseSkill):
    name = "project_tracker"
    description = "專案進度追蹤 — 當使用者想要「檢查專案情況」、「看 Git 狀態」、「檢查 code 改動」時使用"
    commands = ["/projects", "/status", "/diff", "/addproject", "/rmproject"]

    async def handle(self, command: str, args: list[str], user_id: int) -> str:
        if command == "/projects":
            return await self._list_projects()
        elif command == "/status":
            return await self._project_status(args)
        elif command == "/diff":
            return await self._project_diff(args)
        elif command == "/addproject":
            return self._add_project(args)
        elif command == "/rmproject":
            return self._remove_project(args)
        return "未知指令"

    async def _list_projects(self) -> str:
        projects = self.engine.memory.get_projects()
        if not projects:
            return (
                "📂 尚未追蹤任何專案。\n\n"
                "使用 `/addproject <名稱> <路徑>` 來新增。\n"
                "範例: `/addproject davinci /home/kiwi/davinci-ai-video-factory`"
            )

        lines = ["📊 **追蹤中的專案:**\n"]
        for p in projects:
            status = await self._get_git_brief(p["path"])
            desc = f" — {p['description']}" if p["description"] else ""
            lines.append(f"• **{p['name']}**{desc}\n  {status}")

        return "\n".join(lines)

    async def _project_status(self, args: list[str]) -> str:
        if not args:
            return "用法: `/status <專案名稱>`"

        name = args[0]
        path = self.engine.memory.get_project_path(name)
        if not path:
            return f"❌ 找不到專案: {name}\n使用 `/projects` 查看所有專案"

        result = await self._run_git(path, ["log", "--oneline", "-10"])
        branch = await self._run_git(path, ["branch", "--show-current"])
        status = await self._run_git(path, ["status", "--short"])

        return (
            f"📊 **{name}**\n"
            f"📁 `{path}`\n"
            f"🌿 Branch: `{branch.strip()}`\n\n"
            f"📝 **最近 10 筆 commit:**\n```\n{result}\n```\n"
            f"📋 **工作區狀態:**\n```\n{status if status.strip() else '(乾淨)'}\n```"
        )

    async def _project_diff(self, args: list[str]) -> str:
        if not args:
            return "用法: `/diff <專案名稱>`"

        name = args[0]
        path = self.engine.memory.get_project_path(name)
        if not path:
            return f"❌ 找不到專案: {name}"

        diff = await self._run_git(path, ["diff", "--stat", "HEAD~3..HEAD"])
        return f"📋 **{name} — 最近 3 筆改動統計:**\n```\n{diff}\n```"

    def _add_project(self, args: list[str]) -> str:
        if len(args) < 2:
            return "用法: `/addproject <名稱> <路徑> [描述]`"

        name = args[0]
        path = args[1]
        desc = " ".join(args[2:]) if len(args) > 2 else ""

        if not os.path.isdir(path):
            return f"❌ 目錄不存在: {path}"

        self.engine.memory.add_project(name, path, desc)
        return f"✅ 已新增專案: **{name}**\n📁 {path}"

    def _remove_project(self, args: list[str]) -> str:
        if not args:
            return "用法: `/rmproject <名稱>`"
        self.engine.memory.remove_project(args[0])
        return f"✅ 已移除專案: {args[0]}"

    async def _get_git_brief(self, path: str) -> str:
        """Get a one-line git status summary."""
        if not os.path.isdir(path):
            return "⚠️ 目錄不存在"

        branch = await self._run_git(path, ["branch", "--show-current"])
        log = await self._run_git(path, ["log", "--oneline", "-1"])
        return f"🌿 {branch.strip()} | {log.strip()}"

    async def _run_git(self, cwd: str, args: list[str]) -> str:
        """Run a git command and return output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            output = stdout.decode("utf-8", errors="replace").strip()
            return output if output else stderr.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return f"(git 錯誤: {e})"
