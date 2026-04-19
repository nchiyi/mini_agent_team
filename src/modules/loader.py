# src/modules/loader.py
import asyncio
import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable

from src.modules.manifest import ModuleManifest, parse_manifest

logger = logging.getLogger(__name__)

HandlerFn = Callable[..., AsyncIterator[str]]


@dataclass
class LoadedModule:
    manifest: ModuleManifest
    handler: HandlerFn


class ModuleRegistry:
    def __init__(self) -> None:
        self._by_command: dict[str, LoadedModule] = {}
        self._by_name: dict[str, LoadedModule] = {}

    def register(self, module: LoadedModule) -> None:
        for cmd in module.manifest.commands:
            if cmd in self._by_command:
                existing = self._by_command[cmd].manifest.name
                raise ValueError(
                    f"Command conflict: '{cmd}' claimed by both "
                    f"'{existing}' and '{module.manifest.name}'"
                )
            self._by_command[cmd] = module
        self._by_name[module.manifest.name] = module

    def has_command(self, command: str) -> bool:
        return command in self._by_command

    def get_commands(self) -> list[str]:
        return list(self._by_command.keys())

    def get_names(self) -> list[str]:
        return list(self._by_name.keys())

    async def dispatch(
        self, command: str, args: str, user_id: int, channel: str
    ) -> AsyncIterator[str]:
        module = self._by_command.get(command)
        if not module:
            yield f"Module command '{command}' not found."
            return
        timeout = module.manifest.timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                async for chunk in module.handler(command, args, user_id, channel):
                    yield chunk
        except asyncio.TimeoutError:
            yield f"Module '{module.manifest.name}' timed out after {timeout}s."


def load_modules(modules_dir: str) -> ModuleRegistry:
    registry = ModuleRegistry()
    base = Path(modules_dir)
    if not base.exists():
        logger.warning("modules_dir '%s' does not exist, no modules loaded", modules_dir)
        return registry

    for module_dir in sorted(base.iterdir()):
        if not module_dir.is_dir():
            continue
        manifest_path = module_dir / "manifest.yaml"
        handler_path = module_dir / "handler.py"
        if not manifest_path.exists() or not handler_path.exists():
            continue

        try:
            manifest = parse_manifest(manifest_path)
        except Exception as e:
            logger.warning("Failed to parse manifest '%s': %s", manifest_path, e)
            continue

        if not manifest.enabled:
            logger.info("Module '%s' disabled, skipping", manifest.name)
            continue

        try:
            spec = importlib.util.spec_from_file_location(
                f"modules.{manifest.name}.handler", handler_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            handler: HandlerFn = getattr(mod, "handle")
        except Exception as e:
            logger.warning("Failed to load module '%s': %s", manifest.name, e)
            continue

        registry.register(LoadedModule(manifest=manifest, handler=handler))
        logger.info("Loaded module '%s' with commands %s", manifest.name, manifest.commands)

    return registry
