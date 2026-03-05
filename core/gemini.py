"""
Gemini CLI wrapper — executes prompts via `gemini -p`.
"""
import asyncio
import shutil
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # 5 minutes


class GeminiCLI:
    """Wrapper for Gemini CLI non-interactive mode."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.command = "gemini"

    def is_available(self) -> bool:
        """Check if gemini CLI is installed."""
        return shutil.which(self.command) is not None

    async def execute(self, prompt: str, cwd: str, model: Optional[str] = None) -> tuple[str, dict]:
        """
        Execute a prompt via `gemini -p "prompt"`.

        Args:
            prompt: The user's prompt
            cwd: Working directory
            model: Optional model name (e.g. 'gemini-1.5-pro')

        Returns:
            A tuple of (output_text, usage_dict)
        """
        if not self.is_available():
            return (
                "❌ Gemini CLI 未安裝。\n"
                "安裝方法: `npm install -g @google/gemini-cli`\n",
                {}
            )

        args = [self.command]
        if model:
            args.extend(["-m", model])
        args.extend(["-p", prompt])

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout,
            )

            output = stdout.decode("utf-8", errors="replace").strip()
            errors = stderr.decode("utf-8", errors="replace").strip()

            # Rough token estimation (1 token ≈ 4 chars or 0.75 words)
            # This is a fallback if the CLI doesn't provide precise tokens
            est_prompt = len(prompt) // 4
            est_completion = len(output) // 4
            usage = {
                "prompt_tokens": est_prompt,
                "completion_tokens": est_completion,
                "model": model or "gemini-2.0-flash"
            }

            if process.returncode != 0 and errors:
                return f"⚠️ Gemini 執行有錯誤:\n\n{errors}\n\n{output}", usage

            return (output if output else "(無輸出)"), usage

        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            return f"⏰ Gemini 執行超時（{self.timeout}s）", {}
        except FileNotFoundError:
            return "❌ 找不到 gemini CLI，請確認已安裝。", {}
        except Exception as e:
            logger.error(f"Gemini CLI error: {e}")
            return f"❌ 執行失敗: {e}", {}

    async def execute_in_project(self, prompt: str, project_path: str, model: Optional[str] = None) -> tuple[str, dict]:
        """Execute a prompt in a specific project directory."""
        return await self.execute(prompt, project_path, model=model)
