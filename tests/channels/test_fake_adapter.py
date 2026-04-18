# tests/channels/test_fake_adapter.py
import asyncio, pytest, sys
sys.path.insert(0, "tests/channels")
pytestmark = pytest.mark.asyncio


async def test_streaming_bridge_sends_and_edits():
    from fake_adapter import FakeAdapter
    from src.gateway.streaming import StreamingBridge

    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    async def chunks():
        for word in ["hello ", "world ", "!"]:
            yield word
            await asyncio.sleep(0)

    await bridge.stream(user_id=1, chunks=chunks())

    assert len(adapter.sent) == 1
    assert adapter.edits


async def test_streaming_bridge_final_edit_has_full_text():
    from fake_adapter import FakeAdapter
    from src.gateway.streaming import StreamingBridge

    adapter = FakeAdapter()
    bridge = StreamingBridge(adapter, edit_interval=0.0)

    async def chunks():
        for word in ["foo", "bar", "baz"]:
            yield word

    await bridge.stream(user_id=1, chunks=chunks())

    last_edit = list(adapter.edits.values())[-1]
    assert "foobarbaz" == last_edit
