from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def repo_root(base_dir: str | Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir).resolve()
    return Path(__file__).resolve().parents[1]


def roster_path(base_dir: str | Path | None = None) -> Path:
    return repo_root(base_dir) / "roster"


def parse_role_file(path: Path) -> dict[str, Any] | None:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None

    try:
        _, frontmatter, body = content.split("---", 2)
    except ValueError:
        return None

    meta = yaml.safe_load(frontmatter) or {}
    if not isinstance(meta, dict):
        return None

    meta["body"] = body.strip()
    return meta


def load_roles(base_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    roles: dict[str, dict[str, Any]] = {}
    roster_dir = roster_path(base_dir)
    if not roster_dir.exists():
        return roles

    for path in sorted(roster_dir.glob("*.md")):
        meta = parse_role_file(path)
        if not meta:
            continue
        slug = meta.get("slug")
        if not slug:
            continue
        roles[slug] = meta
    return roles


def load_role(role_slug: str, base_dir: str | Path | None = None) -> dict[str, Any] | None:
    if not role_slug:
        return None
    return load_roles(base_dir).get(role_slug)


def available_role_slugs(base_dir: str | Path | None = None) -> list[str]:
    return list(load_roles(base_dir).keys())


def build_role_prompt_prefix(role_slug: str, base_dir: str | Path | None = None) -> str:
    meta = load_role(role_slug, base_dir)
    if not meta:
        return ""

    identity = (meta.get("identity") or "").strip()
    rules = meta.get("rules") or []
    if not isinstance(rules, list):
        rules = [str(rules)]

    parts: list[str] = []
    if identity:
        parts.append(f"[Identity]\n{identity}")
    if rules:
        parts.append("[Rules]\n" + "\n".join(f"- {rule}" for rule in rules))
    parts.append("[Task Brief]")
    return "\n\n".join(parts) + "\n"
