"""B-2 Task 3: BotTurnTracker — cap consecutive bot-to-bot turns per chat."""
from src.gateway.bot_turns import BotTurnTracker


def test_counter_increments_per_bot_turn():
    t = BotTurnTracker(cap=10)
    for _ in range(3):
        t.note_bot_turn(channel="telegram", chat_id=-100)
    assert t.consecutive(channel="telegram", chat_id=-100) == 3
    assert not t.cap_reached(channel="telegram", chat_id=-100)


def test_cap_reached_at_threshold():
    t = BotTurnTracker(cap=3)
    for _ in range(3):
        t.note_bot_turn(channel="telegram", chat_id=-100)
    assert t.cap_reached(channel="telegram", chat_id=-100)


def test_cap_not_reached_just_below_threshold():
    t = BotTurnTracker(cap=3)
    for _ in range(2):
        t.note_bot_turn(channel="telegram", chat_id=-100)
    assert not t.cap_reached(channel="telegram", chat_id=-100)


def test_human_input_resets_counter():
    t = BotTurnTracker(cap=10)
    for _ in range(5):
        t.note_bot_turn(channel="telegram", chat_id=-100)
    t.reset_on_human(channel="telegram", chat_id=-100)
    assert t.consecutive(channel="telegram", chat_id=-100) == 0
    assert not t.cap_reached(channel="telegram", chat_id=-100)


def test_isolated_per_chat():
    t = BotTurnTracker(cap=10)
    t.note_bot_turn(channel="telegram", chat_id=-100)
    t.note_bot_turn(channel="telegram", chat_id=-200)
    t.note_bot_turn(channel="telegram", chat_id=-100)
    assert t.consecutive(channel="telegram", chat_id=-100) == 2
    assert t.consecutive(channel="telegram", chat_id=-200) == 1


def test_isolated_per_channel():
    t = BotTurnTracker(cap=10)
    t.note_bot_turn(channel="telegram", chat_id=-100)
    t.note_bot_turn(channel="discord", chat_id=-100)
    assert t.consecutive(channel="telegram", chat_id=-100) == 1
    assert t.consecutive(channel="discord", chat_id=-100) == 1


def test_reset_isolated_per_chat():
    t = BotTurnTracker(cap=10)
    t.note_bot_turn(channel="telegram", chat_id=-100)
    t.note_bot_turn(channel="telegram", chat_id=-200)
    t.reset_on_human(channel="telegram", chat_id=-100)
    assert t.consecutive(channel="telegram", chat_id=-100) == 0
    assert t.consecutive(channel="telegram", chat_id=-200) == 1


def test_default_cap_is_ten():
    t = BotTurnTracker()
    assert t.cap == 10


def test_consecutive_zero_when_no_turns_recorded():
    t = BotTurnTracker(cap=10)
    assert t.consecutive(channel="telegram", chat_id=-999) == 0
    assert not t.cap_reached(channel="telegram", chat_id=-999)
