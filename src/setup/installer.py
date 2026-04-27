import asyncio
import shutil
import subprocess


_CLI_INSTALL: dict[str, list[str]] = {
    "claude": ["npm", "install", "-g", "@anthropic-ai/claude-code"],
    "codex": ["npm", "install", "-g", "@openai/codex"],
    "gemini": ["npm", "install", "-g", "@google/gemini-cli"],
    "kiro": ["npm", "install", "-g", "@aws/kiro"],
}

_OLLAMA_INSTALL = ["bash", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"]
_OLLAMA_PULL = ["ollama", "pull", "nomic-embed-text"]

# Estimated download sizes shown to users before installation
_CLI_SIZES: dict[str, str] = {
    "claude": "~50MB",
    "codex": "~30MB",
    "gemini": "~40MB",
    "kiro": "~35MB",
}

# ACP npm package mapping: cli name -> (npm package name, binary name)
# Only CLIs that require a separate ACP wrapper are listed here.
# gemini and kiro support ACP natively and are intentionally omitted.
ACP_PACKAGES: dict[str, tuple[str, str]] = {
    "claude": ("@agentclientprotocol/claude-agent-acp", "claude-agent-acp"),
    "codex": ("@zed-industries/codex-acp", "codex-acp"),
}


def is_cli_installed(name: str) -> tuple[bool, str]:
    """Return (installed, version_string).

    version_string is non-empty when the CLI is found and reports a version;
    otherwise it is an empty string.
    """
    path = shutil.which(name)
    if path is None:
        return False, ""
    # Attempt to retrieve version string; best-effort, never raises.
    version = ""
    for flag in ("--version", "-v", "version"):
        try:
            result = subprocess.run(
                [name, flag],
                capture_output=True,
                text=True,
                timeout=5,
            )
            raw = (result.stdout or result.stderr or "").strip().splitlines()
            if raw:
                version = raw[0]
                break
        except Exception:
            continue
    return True, version


async def install_cli_foreground(name: str) -> bool:
    """Install a CLI tool in the foreground, streaming output to the terminal.

    Returns True on success, False on failure.
    """
    cmd = _CLI_INSTALL.get(name)
    if not cmd:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=None,   # inherit terminal stdout
            stderr=None,   # inherit terminal stderr
        )
        await proc.wait()
        return proc.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False


async def install_docker_foreground() -> bool:
    """Install Docker Desktop (macOS via Homebrew) or Docker Engine (Linux via official script).

    Returns True on success, False on failure or unsupported platform.
    """
    import sys
    try:
        if sys.platform == "darwin":
            brew = shutil.which("brew")
            if not brew:
                return False
            proc = await asyncio.create_subprocess_exec(
                brew, "install", "--cask", "docker",
                stdout=None,
                stderr=None,
            )
            await proc.wait()
            return proc.returncode == 0
        else:
            # Linux: official Docker install script
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", "curl -fsSL https://get.docker.com | sh",
                stdout=None,
                stderr=None,
            )
            await proc.wait()
            return proc.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False


async def install_ollama_foreground() -> bool:
    """Install Ollama and pull the embedding model, streaming output to the terminal.

    Returns True on success, False on failure.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *_OLLAMA_INSTALL,
            stdout=None,   # inherit terminal stdout
            stderr=None,   # inherit terminal stderr
        )
        await proc.wait()
        if proc.returncode != 0:
            return False
        proc2 = await asyncio.create_subprocess_exec(
            *_OLLAMA_PULL,
            stdout=None,
            stderr=None,
        )
        await proc2.wait()
        return proc2.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False


def is_acp_installed(cli: str) -> tuple[bool, str]:
    """Return (satisfied, binary_name) for the ACP package of a given CLI.

    Returns (True, "") for CLIs with no ACP package requirement (e.g. gemini).
    """
    entry = ACP_PACKAGES.get(cli)
    if entry is None:
        return True, ""
    _npm_pkg, binary = entry
    return shutil.which(binary) is not None, binary


def is_npm_available() -> bool:
    """Return True if npm is found in PATH."""
    return shutil.which("npm") is not None


async def install_acp_foreground(cli: str) -> bool:
    """Install the ACP npm package for *cli*, streaming output to terminal.

    Returns True on success or when no package is required.
    Returns False when npm is missing or the install command fails.
    """
    entry = ACP_PACKAGES.get(cli)
    if entry is None:
        return True
    npm_pkg, _binary = entry
    npm = shutil.which("npm")
    if npm is None:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            npm, "install", "-g", npm_pkg,
            stdout=None,
            stderr=None,
        )
        await proc.wait()
        return proc.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False
