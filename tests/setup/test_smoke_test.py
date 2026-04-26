"""
Unit tests for src.setup.smoke_test — Phase 3 smoke test.

All network I/O and subprocess I/O is mocked.
"""

from __future__ import annotations

import asyncio
import json
import sys
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.setup.smoke_test import (
    wait_for_bot_ready,
    send_verification_telegram,
    wait_for_ok_reply_telegram,
    run_smoke_test,
)
from src.setup.state import WizardState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stdout(*lines: str) -> AsyncMock:
    """
    Build a mock asyncio.subprocess.Process with a mocked stdout
    that yields the provided lines (as bytes) when iterated.
    """
    encoded = [ln.encode() + b"\n" for ln in lines]

    async def _aiter(self):  # noqa: D401
        for chunk in encoded:
            yield chunk

    mock_stdout = MagicMock()
    mock_stdout.__aiter__ = _aiter
    return mock_stdout


def _make_proc(*lines: str, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = _make_stdout(*lines)
    return proc


# ---------------------------------------------------------------------------
# 1. wait_for_bot_ready — stdout contains "bot started" → True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_for_bot_ready_found():
    proc = _make_proc("Initialising…", "Bot started", "Listening…")
    result = await wait_for_bot_ready(proc, timeout=5)
    assert result is True


# ---------------------------------------------------------------------------
# 2. wait_for_bot_ready — no ready line, timeout → False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_for_bot_ready_timeout():
    # Stream never yields a ready signal — simulate via empty stdout.
    # We need it to exhaust the stream so the function returns False
    # (no timeout needed because the stream ends).
    proc = _make_proc("Some random log line", "Another line without signal")
    result = await wait_for_bot_ready(proc, timeout=5)
    assert result is False


# ---------------------------------------------------------------------------
# 3. send_verification_telegram — mock urllib, check correct endpoint called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_verification_telegram_calls_correct_endpoint():
    token = "123456:ABCDEFGHIJKLMNOPabcdefghijklmnopqrs"
    user_id = 99999

    response_body = json.dumps({"ok": True, "result": {}}).encode()

    class _FakeResp:
        def read(self):
            return response_body
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    captured: dict = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data)
        return _FakeResp()

    with patch("src.setup.smoke_test.urllib.request.urlopen", side_effect=_fake_urlopen):
        result = await send_verification_telegram(token, user_id)

    assert result is True
    assert captured["url"] == f"https://api.telegram.org/bot{token}/sendMessage"
    assert captured["data"]["chat_id"] == user_id
    assert "ok" in captured["data"]["text"].lower() or "verify" in captured["data"]["text"].lower()


# ---------------------------------------------------------------------------
# 4. wait_for_ok_reply_telegram — getUpdates returns "ok" message → True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_for_ok_reply_telegram_success():
    token = "123456:ABCDEFGHIJKLMNOPabcdefghijklmnopqrs"
    user_id = 42

    ok_update = {
        "ok": True,
        "result": [
            {
                "update_id": 100,
                "message": {
                    "from": {"id": user_id},
                    "text": "ok",
                },
            }
        ],
    }

    class _FakeResp:
        def __init__(self, body: bytes):
            self._body = body
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    call_count = [0]

    def _fake_urlopen(url, timeout=None):
        call_count[0] += 1
        return _FakeResp(json.dumps(ok_update).encode())

    with patch("src.setup.smoke_test.urllib.request.urlopen", side_effect=_fake_urlopen):
        result = await wait_for_ok_reply_telegram(token, user_id, timeout=10)

    assert result is True
    assert call_count[0] >= 1


# ---------------------------------------------------------------------------
# 5. wait_for_ok_reply_telegram — timeout with no reply → False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_for_ok_reply_telegram_timeout():
    token = "123456:ABCDEFGHIJKLMNOPabcdefghijklmnopqrs"
    user_id = 42

    empty_response = json.dumps({"ok": True, "result": []}).encode()

    class _FakeResp:
        def read(self):
            return empty_response
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    with patch("src.setup.smoke_test.urllib.request.urlopen", return_value=_FakeResp()):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Patch get_event_loop().time() to fast-forward past timeout
            real_loop = asyncio.get_event_loop()
            times = iter([0.0, 0.0, 200.0])  # third call > timeout=2
            with patch.object(real_loop, "time", side_effect=lambda: next(times)):
                result = await wait_for_ok_reply_telegram(token, user_id, timeout=2)

    assert result is False


# ---------------------------------------------------------------------------
# 6. run_smoke_test — all success → True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_smoke_test_all_success():
    state = WizardState(
        channels=["telegram"],
        telegram_token="123456:ABCDEFGHIJKLMNOPabcdefghijklmnopqrs",
        allowed_user_ids=[42],
    )
    proc = _make_proc("Gateway ready")

    with patch("src.setup.smoke_test.send_verification_telegram", new_callable=AsyncMock, return_value=True), \
         patch("src.setup.smoke_test.wait_for_ok_reply_telegram", new_callable=AsyncMock, return_value=True):
        result = await run_smoke_test(state, proc)

    assert result is True


# ---------------------------------------------------------------------------
# 7. run_smoke_test — ready timeout → False + diagnostic printed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_smoke_test_ready_timeout(capsys):
    state = WizardState(
        channels=["telegram"],
        telegram_token="123456:ABCDEFGHIJKLMNOPabcdefghijklmnopqrs",
        allowed_user_ids=[42],
    )
    # Empty stdout: bot never emits a ready signal
    proc = _make_proc()  # no lines → stream ends → wait_for_bot_ready returns False
    proc.returncode = 1

    result = await run_smoke_test(state, proc)

    assert result is False
    captured = capsys.readouterr()
    assert "Smoke test failed" in captured.out
    assert "Suggested fixes" in captured.out
