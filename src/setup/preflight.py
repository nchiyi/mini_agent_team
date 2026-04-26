"""Pre-flight checks — run once before any wizard step writes to disk."""
import asyncio
import os
import shutil
import sys

_G = "\033[32m"
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
    """Run all pre-flight checks; sys.exit(1) if any fail."""
    print(f"\n{_B}[0/9] Pre-flight Checks{_X}")

    results: list[tuple[bool, str]] = []

    # Synchronous checks
    results.append(_check_python())
    results.append(_check_disk(cwd))

    # Parallel network probes
    net_results = await _check_network()
    results.extend(net_results)

    # venv check
    results.append(_check_venv(cwd))

    # Print all results before deciding to exit
    any_failed = False
    for ok, msg in results:
        if ok:
            print(f"  {_G}✓ {msg}{_X}")
        else:
            print(f"  {_R}✗ {msg}{_X}")
            any_failed = True

    if any_failed:
        sys.exit(1)
