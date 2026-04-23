# tests/modules/test_loader.py
import sys, pytest
from pathlib import Path


def _make_module(base: Path, name: str, commands: list[str],
                 enabled: bool = True, handler_code: str = "") -> None:
    d = base / name
    d.mkdir(parents=True)
    manifest = f"name: {name}\ncommands: {commands}\nenabled: {str(enabled).lower()}\ntimeout_seconds: 5\n"
    (d / "manifest.yaml").write_text(manifest)
    default_handler = (
        "from typing import AsyncIterator\n"
        "async def handle(command, args, user_id, channel) -> AsyncIterator[str]:\n"
        "    yield f'handled {command} {args}'\n"
    )
    (d / "handler.py").write_text(handler_code or default_handler)


def test_load_modules_empty_dir(tmp_path):
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []
    assert reg.get_commands() == []


def test_load_modules_nonexistent_dir(tmp_path):
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path / "no_such_dir"))
    assert reg.get_names() == []


def test_load_modules_finds_valid_module(tmp_path):
    _make_module(tmp_path, "alpha", ["/alpha"])
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert "alpha" in reg.get_names()
    assert "/alpha" in reg.get_commands()


def test_load_modules_skips_disabled(tmp_path):
    _make_module(tmp_path, "off_mod", ["/off"], enabled=False)
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []


def test_load_modules_skips_missing_handler(tmp_path):
    d = tmp_path / "nohandler"
    d.mkdir()
    (d / "manifest.yaml").write_text("name: nohandler\ncommands: [/nh]\n")
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []


def test_load_modules_skips_bad_import(tmp_path):
    _make_module(tmp_path, "broken", ["/broken"],
                 handler_code="import totally_fake_package_xyz\n")
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []


def test_load_modules_conflict_raises(tmp_path):
    _make_module(tmp_path, "mod_a", ["/search"])
    _make_module(tmp_path, "mod_b", ["/search"])
    from src.modules.loader import load_modules
    with pytest.raises(ValueError, match="conflict"):
        load_modules(str(tmp_path))


def test_load_modules_skips_dir_without_manifest(tmp_path):
    d = tmp_path / "nomanifest"
    d.mkdir()
    (d / "handler.py").write_text("async def handle(*a): yield 'x'\n")
    from src.modules.loader import load_modules
    reg = load_modules(str(tmp_path))
    assert reg.get_names() == []


def test_real_agency_module_loads():
    from src.modules.loader import load_modules
    repo_root = Path(__file__).resolve().parents[2]
    reg = load_modules(str(repo_root / "modules"))
    assert "agency" in reg.get_names()
    assert "/agency" in reg.get_commands()
