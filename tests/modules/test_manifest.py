# tests/modules/test_manifest.py
import pytest
from pathlib import Path
from src.modules.manifest import ModuleManifest, parse_manifest


def _write(tmp_path, content: str) -> Path:
    p = tmp_path / "manifest.yaml"
    p.write_text(content)
    return p


def test_parse_full_manifest(tmp_path):
    p = _write(tmp_path, """
name: web_search
version: 1.2.3
commands: [/search, /web]
description: Search the web
dependencies: [duckduckgo-search]
enabled: true
timeout_seconds: 30
""")
    m = parse_manifest(p)
    assert m.name == "web_search"
    assert m.version == "1.2.3"
    assert m.commands == ["/search", "/web"]
    assert m.description == "Search the web"
    assert m.dependencies == ["duckduckgo-search"]
    assert m.enabled is True
    assert m.timeout_seconds == 30


def test_parse_minimal_manifest_uses_defaults(tmp_path):
    p = _write(tmp_path, "name: mymod\ncommands: [/mymod]\n")
    m = parse_manifest(p)
    assert m.name == "mymod"
    assert m.version == "0.0.0"
    assert m.description == ""
    assert m.dependencies == []
    assert m.enabled is True
    assert m.timeout_seconds == 30


def test_parse_disabled_module(tmp_path):
    p = _write(tmp_path, "name: off\ncommands: [/off]\nenabled: false\n")
    m = parse_manifest(p)
    assert m.enabled is False


def test_parse_missing_name_raises(tmp_path):
    p = _write(tmp_path, "commands: [/x]\n")
    with pytest.raises(KeyError):
        parse_manifest(p)


def test_parse_missing_commands_raises(tmp_path):
    p = _write(tmp_path, "name: nocommands\n")
    with pytest.raises(KeyError):
        parse_manifest(p)
