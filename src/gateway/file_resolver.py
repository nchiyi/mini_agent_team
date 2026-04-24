# src/gateway/file_resolver.py
"""
Lightweight file resolver: maps natural language file references to real paths.
Uses find/git ls-files (depth 2) to avoid token waste.
"""
import asyncio
import re
from pathlib import Path

_NL_REFS = re.compile(
    r"\b(the\s+)?"
    r"(main|entry[\s_]?point|config(?:uration)?|schema|readme|makefile|"
    r"dockerfile|compose|setup|requirements?|pyproject|package(?:\.json)?)"
    r"\b",
    re.IGNORECASE,
)

_KNOWN_NAMES: dict[str, list[str]] = {
    "main": ["main.py", "main.ts", "main.go", "main.js", "index.py", "index.ts", "index.js", "app.py"],
    "entry": ["main.py", "app.py", "index.py", "index.ts", "index.js", "server.py"],
    "config": ["config.toml", "config.yaml", "config.yml", "config.json", ".env"],
    "schema": ["schema.py", "schema.sql", "schema.json", "models.py"],
    "readme": ["README.md", "README.rst", "README.txt"],
    "makefile": ["Makefile", "makefile"],
    "dockerfile": ["Dockerfile"],
    "compose": ["docker-compose.yml", "docker-compose.yaml", "compose.yml"],
    "setup": ["setup.py", "setup.cfg", "setup.sh"],
    "requirements": ["requirements.txt", "requirements.in"],
    "pyproject": ["pyproject.toml"],
    "package": ["package.json"],
}


async def _list_files(cwd: str, max_depth: int = 2) -> list[str]:
    """List files up to max_depth using git ls-files, falling back to find."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "ls-files",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        files = [
            f for f in out.decode().splitlines()
            if f.count("/") < max_depth
        ]
        if files:
            return files
    except Exception:
        pass

    try:
        proc = await asyncio.create_subprocess_exec(
            "find", ".", "-maxdepth", str(max_depth), "-type", "f",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        return [f.lstrip("./") for f in out.decode().splitlines() if f.startswith("./")]
    except Exception:
        return []


async def resolve_file_refs(prompt: str, cwd: str) -> str:
    """
    Scan prompt for natural-language file references and append resolved paths.
    Returns the original prompt unchanged if no refs found or resolution fails.
    """
    match = _NL_REFS.search(prompt)
    if not match:
        return prompt

    try:
        files = await _list_files(cwd)
    except Exception:
        return prompt

    file_set = {Path(f).name.lower(): f for f in reversed(files)}
    resolved: list[str] = []

    for m in _NL_REFS.finditer(prompt):
        key = m.group(2).lower().replace(" ", "").replace("_", "")
        candidates = _KNOWN_NAMES.get(key, [])
        for candidate in candidates:
            actual = file_set.get(candidate.lower())
            if actual and actual not in resolved:
                resolved.append(actual)
                break

    if not resolved:
        return prompt

    ref_note = "\n\n[Resolved file references: " + ", ".join(resolved) + "]"
    return prompt + ref_note
