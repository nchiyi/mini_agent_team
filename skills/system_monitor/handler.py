import asyncio
from typing import AsyncIterator


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    try:
        import psutil
        cpu, mem, disk = await asyncio.to_thread(
            lambda: (
                psutil.cpu_percent(interval=0.5),
                psutil.virtual_memory(),
                psutil.disk_usage("/"),
            )
        )
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
