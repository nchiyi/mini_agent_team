"""
Base agent interface for AI CLI tools.
"""
import asyncio
import os
from abc import ABC, abstractmethod

from config import AGENT_TIMEOUT


class BaseAgent(ABC):
    """Base class for AI CLI agent wrappers."""

    name: str = "base"
    command: str = ""

    @abstractmethod
    def build_args(self, prompt: str) -> list[str]:
        """Build the CLI argument list for the given prompt."""
        ...

    async def execute(self, prompt: str, cwd: str) -> str:
        """
        Execute a prompt via the CLI agent.

        Args:
            prompt: The user's prompt/instruction
            cwd: Working directory for the agent

        Returns:
            The agent's text output
        """
        if not self.is_available():
            return f"❌ {self.name} CLI 未安裝或不在 PATH 中。"

        args = self.build_args(prompt)
        full_cmd = [self.command] + args

        try:
            process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=AGENT_TIMEOUT,
            )

            output = stdout.decode("utf-8", errors="replace").strip()
            errors = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode != 0 and errors:
                return f"⚠️ {self.name} 執行有錯誤:\n\n{errors}\n\n{output}"

            return output if output else "(無輸出)"

        except asyncio.TimeoutError:
            process.kill()
            return f"⏰ {self.name} 執行超時（{AGENT_TIMEOUT}s）"
        except FileNotFoundError:
            return f"❌ 找不到 {self.command}，請確認已安裝。"
        except Exception as e:
            return f"❌ 執行失敗: {e}"

    def is_available(self) -> bool:
        """Check if the CLI tool is installed and accessible."""
        import shutil
        return shutil.which(self.command) is not None
