# src/skills/loader.py
import asyncio
import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable

from src.skills.manifest import SkillManifest, parse_manifest

logger = logging.getLogger(__name__)

HandlerFn = Callable[..., AsyncIterator[str]]


@dataclass
class LoadedSkill:
    manifest: SkillManifest
    handler: HandlerFn

# Backward-compatible alias
LoadedModule = LoadedSkill


class SkillRegistry:
    def __init__(self) -> None:
        self._by_command: dict[str, LoadedSkill] = {}
        self._by_name: dict[str, LoadedSkill] = {}

    def register(self, skill: LoadedSkill) -> None:
        for cmd in skill.manifest.commands:
            if cmd in self._by_command:
                existing = self._by_command[cmd].manifest.name
                raise ValueError(
                    f"Command conflict: '{cmd}' claimed by both "
                    f"'{existing}' and '{skill.manifest.name}'"
                )
            self._by_command[cmd] = skill
        self._by_name[skill.manifest.name] = skill

    def has_command(self, command: str) -> bool:
        return command in self._by_command

    def get_commands(self) -> list[str]:
        return list(self._by_command.keys())

    def get_names(self) -> list[str]:
        return list(self._by_name.keys())

    async def dispatch(
        self, command: str, args: str, user_id: int, channel: str
    ) -> AsyncIterator[str]:
        skill = self._by_command.get(command)
        if not skill:
            yield f"Skill command '{command}' not found."
            return
        timeout = skill.manifest.timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                async for chunk in skill.handler(command, args, user_id, channel):
                    yield chunk
        except asyncio.TimeoutError:
            yield f"Skill '{skill.manifest.name}' timed out after {timeout}s."

# Backward-compatible aliases
ModuleRegistry = SkillRegistry


def load_skills(skills_dir: str) -> SkillRegistry:
    registry = SkillRegistry()
    base = Path(skills_dir)
    if not base.exists():
        logger.warning("skills_dir '%s' does not exist, no skills loaded", skills_dir)
        return registry

    for skill_dir in sorted(base.iterdir()):
        if not skill_dir.is_dir():
            continue
        manifest_path = skill_dir / "manifest.yaml"
        handler_path = skill_dir / "handler.py"
        if not manifest_path.exists() or not handler_path.exists():
            continue

        try:
            manifest = parse_manifest(manifest_path)
        except Exception as e:
            logger.warning("Failed to parse manifest '%s': %s", manifest_path, e)
            continue

        if not manifest.enabled:
            logger.info("Skill '%s' disabled, skipping", manifest.name)
            continue

        try:
            spec = importlib.util.spec_from_file_location(
                f"skills.{manifest.name}.handler", handler_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            handler: HandlerFn = getattr(mod, "handle")
        except Exception as e:
            logger.warning("Failed to load skill '%s': %s", manifest.name, e)
            continue

        registry.register(LoadedSkill(manifest=manifest, handler=handler))
        logger.info("Loaded skill '%s' with commands %s", manifest.name, manifest.commands)

    return registry

# Backward-compatible alias
load_modules = load_skills
