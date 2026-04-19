import pytest
from unittest.mock import patch, AsyncMock, MagicMock
pytestmark = pytest.mark.asyncio


async def _collect(gen) -> list[str]:
    return [c async for c in gen]


async def test_vision_empty_args_shows_usage():
    import sys
    sys.modules.setdefault("httpx", MagicMock())
    import importlib
    import modules.vision.handler as vh
    importlib.reload(vh)

    chunks = await _collect(vh.handle("/describe", "  ", 1, "tg"))
    assert any("Usage" in c for c in chunks)


async def test_vision_calls_ollama_with_url():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"response": "A beautiful landscape."}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_httpx = MagicMock()
    mock_httpx.AsyncClient.return_value = mock_client

    with patch.dict("sys.modules", {"httpx": mock_httpx}):
        import importlib
        import modules.vision.handler as vh
        importlib.reload(vh)

        chunks = await _collect(
            vh.handle("/describe", "https://example.com/img.jpg", 1, "tg")
        )
        combined = "".join(chunks)
        assert "A beautiful landscape." in combined


async def test_vision_no_httpx_yields_install_hint():
    import sys
    # Remove httpx from sys.modules to force ImportError
    saved_httpx = sys.modules.pop("httpx", None)
    try:
        # Temporarily block httpx imports
        sys.modules["httpx"] = None
        import importlib
        import modules.vision.handler as vh
        importlib.reload(vh)

        chunks = await _collect(vh.handle("/describe", "https://example.com/img.jpg", 1, "tg"))
        combined = "".join(chunks)
        assert "httpx" in combined
    finally:
        # Restore httpx state
        if saved_httpx is not None:
            sys.modules["httpx"] = saved_httpx
        else:
            sys.modules.pop("httpx", None)
