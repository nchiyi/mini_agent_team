# src/skills/manifest.py
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class SkillManifest:
    name: str
    version: str
    commands: list[str]
    description: str
    dependencies: list[str]
    enabled: bool
    timeout_seconds: int


# Backward-compatible alias
ModuleManifest = SkillManifest


def parse_manifest(path: Path) -> SkillManifest:
    with open(path) as f:
        data = yaml.safe_load(f)
    commands = data["commands"]
    if not isinstance(commands, list):
        raise ValueError(f"'commands' must be a list, got {type(commands).__name__}")
    return SkillManifest(
        name=data["name"],
        version=data.get("version", "0.0.0"),
        commands=commands,
        description=data.get("description", ""),
        dependencies=data.get("dependencies", []),
        enabled=data.get("enabled", True),
        timeout_seconds=data.get("timeout_seconds", 30),
    )
