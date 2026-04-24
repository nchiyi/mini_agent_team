# tests/gateway/test_file_resolver.py
import pytest
from pathlib import Path
from src.gateway.file_resolver import resolve_file_refs


@pytest.mark.asyncio
async def test_no_ref_returns_unchanged(tmp_path):
    result = await resolve_file_refs("please summarise the data", str(tmp_path))
    assert result == "please summarise the data"


@pytest.mark.asyncio
async def test_resolves_main_file(tmp_path):
    (tmp_path / "main.py").write_text("# main")
    result = await resolve_file_refs("fix the bug in the main file", str(tmp_path))
    assert "main.py" in result


@pytest.mark.asyncio
async def test_resolves_readme(tmp_path):
    (tmp_path / "README.md").write_text("# readme")
    result = await resolve_file_refs("update the readme", str(tmp_path))
    assert "README.md" in result


@pytest.mark.asyncio
async def test_no_match_returns_unchanged(tmp_path):
    # Prompt mentions "main" but no main.py exists
    result = await resolve_file_refs("fix the main issue", str(tmp_path))
    assert "[Resolved" not in result


@pytest.mark.asyncio
async def test_nonexistent_cwd_returns_unchanged():
    result = await resolve_file_refs("edit the main file", "/nonexistent_path_xyz")
    assert result == "edit the main file"
