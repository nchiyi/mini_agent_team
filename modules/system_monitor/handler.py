from typing import AsyncIterator


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        lines = [
            f"CPU: {cpu:.1f}%",
            f"RAM: {mem.used / 1024**3:.1f}GB / {mem.total / 1024**3:.1f}GB ({mem.percent:.1f}%)",
            f"Disk: {disk.used / 1024**3:.1f}GB / {disk.total / 1024**3:.1f}GB ({disk.percent:.1f}%)",
        ]
        yield "\n".join(lines)
    except ImportError:
        yield "psutil not installed. Run: pip install psutil"
    except Exception as e:
        yield f"System info error: {e}"
