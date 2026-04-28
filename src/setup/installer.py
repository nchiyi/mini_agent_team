import asyncio
import shutil
import subprocess
import sys


def _find_brew() -> str | None:
    """Return the path to brew, checking common macOS locations."""
    for candidate in (
        shutil.which("brew"),
        "/opt/homebrew/bin/brew",   # Apple Silicon
        "/usr/local/bin/brew",      # Intel
    ):
        if candidate and shutil.which(candidate) or (candidate and __import__("os").path.isfile(candidate)):
            return candidate
    return None


_CLI_INSTALL: dict[str, list[str]] = {
    "claude": ["npm", "install", "-g", "@anthropic-ai/claude-code"],
    "codex": ["npm", "install", "-g", "@openai/codex"],
    "gemini": ["npm", "install", "-g", "@google/gemini-cli"],
}

_OLLAMA_INSTALL = ["bash", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"]
_OLLAMA_PULL = ["ollama", "pull", "nomic-embed-text"]

# Estimated download sizes shown to users before installation
_CLI_SIZES: dict[str, str] = {
    "claude": "~50MB",
    "codex": "~30MB",
    "gemini": "~40MB",
}

# ACP npm package mapping: cli name -> (npm package name, binary name)
# Only CLIs that require a separate ACP wrapper are listed here.
# gemini supports ACP natively and is intentionally omitted.
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


async def install_colima_foreground() -> bool:
    """Install Colima + Docker CLI via Homebrew and start the Colima VM.

    Colima is a lightweight Docker Engine for macOS that does not require
    the Docker Desktop GUI.  Returns True when `docker info` is reachable
    after installation.
    """
    brew = _find_brew()
    if not brew:
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            brew, "install", "colima", "docker",
            stdout=None,
            stderr=None,
        )
        await proc.wait()
        if proc.returncode != 0:
            return False
        colima = shutil.which("colima")
        if not colima:
            import os as _os
            for _c in ("/opt/homebrew/bin/colima", "/usr/local/bin/colima"):
                if _os.path.isfile(_c):
                    colima = _c
                    break
            else:
                colima = "/opt/homebrew/bin/colima"
        proc2 = await asyncio.create_subprocess_exec(
            colima, "start",
            stdout=None,
            stderr=None,
        )
        await proc2.wait()
        return proc2.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False


async def install_docker_foreground() -> bool:
    """Install Docker Desktop (macOS via Homebrew cask) or Docker Engine (Linux).

    On macOS this installs the full Docker Desktop GUI app.
    For a lightweight alternative, use install_colima_foreground().
    Returns True on success.
    """
    try:
        if sys.platform == "darwin":
            brew = _find_brew()
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
