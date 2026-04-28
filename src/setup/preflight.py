"""Pre-flight checks — run once before any wizard step writes to disk."""
import asyncio
import os
import shutil
import subprocess
import sys

_G = "\033[32m"
_Y = "\033[33m"
_R = "\033[31m"
_B = "\033[1m"
_X = "\033[0m"

# Minimum requirements
_MIN_PYTHON = (3, 11)
_MIN_DISK_GB = 8.0

# Hosts to test for network reachability
_NETWORK_HOSTS = [
    ("api.telegram.org", "Telegram Bot API"),
    ("discord.com", "Discord API"),
    ("registry.npmjs.org", "npm registry"),
    ("pypi.org", "PyPI"),
]


def _detect_distro() -> str:
    """Return short distro id (ubuntu, debian, fedora, arch, alpine, darwin, ...)."""
    if sys.platform == "darwin":
        return "darwin"
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.partition("=")[2].strip().strip('"').lower()
    except OSError:
        pass
    return "unknown"


def _check_service_manager() -> tuple[bool, str]:
    """Detect available service manager (informational, not a hard requirement).

    macOS → launchd, most Linux → systemd-user, otherwise warn the user that
    only foreground / docker deploy modes will be available.
    """
    if sys.platform == "darwin":
        return True, "launchd available (macOS)"
    # Probe systemd-user session (PID 1 of `--user`).
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True, timeout=5,
        )
        # Returncodes: 0=running, 1=degraded, 4=no-such-unit etc.
        if r.returncode in (0, 1):
            return True, "systemd --user session active"
        return (
            False,
            "systemd --user session not running — systemd deploy mode "
            "will be unavailable; foreground/docker still OK. "
            "Fix: loginctl enable-linger $USER && systemctl --user start dbus.service",
        )
    except FileNotFoundError:
        return (
            False,
            "systemctl not found — non-systemd Linux. "
            "Use foreground or docker deploy mode.",
        )
    except subprocess.TimeoutExpired:
        return False, "systemctl --user timed out (rare)"


def _check_docker() -> tuple[bool, str]:
    """Probe `docker info` — informational, only required if user picks Docker mode."""
    if not shutil.which("docker"):
        return False, "docker not installed (only required for Docker deploy mode)"
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            return True, "docker daemon reachable"
        return (
            False,
            "docker installed but daemon not running. "
            "On macOS: open -a Docker. "
            "On Linux: sudo systemctl start docker (or use Colima).",
        )
    except subprocess.TimeoutExpired:
        return False, "docker info timed out (daemon hung?)"


def _check_python() -> tuple[bool, str]:
    """Return (ok, message) for Python version check."""
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= _MIN_PYTHON:
        return True, f"Python {version_str}"
    needed = ".".join(str(x) for x in _MIN_PYTHON)
    return (
        False,
        f"Python {version_str} found, need ≥{needed}. "
        f"Fix: pyenv install {needed}",
    )


def _check_disk(cwd: str = "/") -> tuple[bool, str]:
    """Return (ok, message) for disk space check on the partition containing cwd."""
    stat = shutil.disk_usage(cwd)
    free_gb = stat.free / (1024**3)
    if free_gb >= _MIN_DISK_GB:
        return True, f"Disk: {free_gb:.1f} GB free (need ≥{_MIN_DISK_GB:.0f} GB)"
    return (
        False,
        f"Disk: only {free_gb:.1f} GB free — need ≥{_MIN_DISK_GB:.0f} GB. "
        f"Free up space and retry.",
    )


async def _probe_host(host: str, port: int = 443, timeout: float = 5.0) -> bool:
    """Return True if TCP connection to host:port succeeds within timeout."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _check_network() -> list[tuple[bool, str]]:
    """Probe all network hosts in parallel; return list of (ok, message)."""
    tasks = [asyncio.create_task(_probe_host(host)) for host, _ in _NETWORK_HOSTS]
    results = await asyncio.gather(*tasks)
    items: list[tuple[bool, str]] = []
    for (host, _label), ok in zip(_NETWORK_HOSTS, results):
        if ok:
            items.append((True, f"{host} reachable"))
        else:
            items.append((
                False,
                f"{host} unreachable — check network/firewall and retry",
            ))
    return items


def _check_venv(cwd: str) -> tuple[bool, str]:
    """Return (ok, message) for venv existence check."""
    python_path = os.path.join(cwd, "venv", "bin", "python3")
    if os.path.exists(python_path):
        return True, f"venv found at {os.path.relpath(python_path, cwd)}"
    rel = os.path.join(".", "venv", "bin", "python3")
    return (
        False,
        f"venv not found at {rel} — run: "
        f"python3 -m venv venv && venv/bin/pip install -r requirements.txt",
    )


async def run_preflight(cwd: str) -> None:
    """Run all pre-flight checks. Hard failures exit 1; soft warnings print only.

    Hard requirements (must pass): Python ≥3.11, disk space, network, venv.
    Soft warnings (informational): service manager, Docker, distro detection.
    """
    print(f"\n{_B}[0/9] Pre-flight Checks{_X}")
    print(f"  Platform: {sys.platform} ({_detect_distro()})")

    hard: list[tuple[bool, str]] = []
    soft: list[tuple[bool, str]] = []

    # Hard requirements
    hard.append(_check_python())
    hard.append(_check_disk(cwd))
    net_results = await _check_network()
    hard.extend(net_results)
    hard.append(_check_venv(cwd))

    # Soft / informational
    soft.append(_check_service_manager())
    soft.append(_check_docker())

    any_failed = False
    for ok, msg in hard:
        if ok:
            print(f"  {_G}✓ {msg}{_X}")
        else:
            print(f"  {_R}✗ {msg}{_X}")
            any_failed = True
    for ok, msg in soft:
        if ok:
            print(f"  {_G}✓ {msg}{_X}")
        else:
            # Soft checks print as warnings (yellow), not errors — wizard
            # continues and the user simply won't see those deploy options.
            print(f"  {_Y}⚠ {msg}{_X}")

    if any_failed:
        sys.exit(1)
