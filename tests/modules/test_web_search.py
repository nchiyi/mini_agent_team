import asyncio, sys, pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_web_search_returns_results():
    fake_results = [
        {"title": "Python docs", "href": "https://python.org", "body": "Python is great."},
        {"title": "Real Python", "href": "https://realpython.com", "body": "Tutorials."},
    ]

    mock_ddgs = MagicMock()
    mock_ddgs.return_value.__enter__ = MagicMock(return_value=mock_ddgs.return_value)
    mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
    mock_ddgs.return_value.text = MagicMock(return_value=fake_results)

    with patch.dict("sys.modules", {"duckduckgo_search": MagicMock(DDGS=mock_ddgs)}):
        import importlib
        import modules.web_search.handler as wsh
        importlib.reload(wsh)

        chunks = await _collect(wsh.handle("/search", "python tutorial", 1, "tg"))
        combined = "".join(chunks)
        assert "Python docs" in combined
        assert "https://python.org" in combined


async def test_web_search_empty_args_shows_usage():
    import importlib, sys
    sys.modules.setdefault("duckduckgo_search", MagicMock())
    import modules.web_search.handler as wsh
    importlib.reload(wsh)

    chunks = await _collect(wsh.handle("/search", "  ", 1, "tg"))
    assert any("Usage" in c for c in chunks)


async def test_web_search_no_results():
    mock_ddgs = MagicMock()
    mock_ddgs.return_value.text = MagicMock(return_value=[])

    with patch.dict("sys.modules", {"duckduckgo_search": MagicMock(DDGS=mock_ddgs)}):
        import importlib
        import modules.web_search.handler as wsh
        importlib.reload(wsh)

        chunks = await _collect(wsh.handle("/search", "xyzzy", 1, "tg"))
        assert any("No results" in c for c in chunks)
