import asyncio
import shutil


_CLI_INSTALL: dict[str, list[str]] = {
    "claude": ["npm", "install", "-g", "@anthropic-ai/claude-code"],
    "codex": ["npm", "install", "-g", "@openai/codex"],
    "gemini": ["npm", "install", "-g", "@google/gemini-cli"],
    "kiro": ["npm", "install", "-g", "@aws/kiro"],
}

_OLLAMA_INSTALL = ["bash", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"]
_OLLAMA_PULL = ["ollama", "pull", "nomic-embed-text"]


def is_cli_installed(name: str) -> bool:
    return shutil.which(name) is not None


async def install_cli(name: str) -> tuple[str, bool]:
    cmd = _CLI_INSTALL.get(name)
    if not cmd:
        return name, False
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.wait()
        return name, proc.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return name, False


async def install_ollama() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            *_OLLAMA_INSTALL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc.wait()
        if proc.returncode != 0:
            return False
        proc2 = await asyncio.create_subprocess_exec(
            *_OLLAMA_PULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        await proc2.wait()
        return proc2.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False


async def progress_reporter(
    tasks: list[asyncio.Task], names: list[str], interval: int = 30
) -> None:
    elapsed = 0
    while True:
        await asyncio.sleep(interval)
        elapsed += interval
        pending = [names[i] for i, t in enumerate(tasks) if not t.done()]
        if not pending:
            break
        print(f"[background] Still installing: {', '.join(pending)} ({elapsed}s elapsed)")
