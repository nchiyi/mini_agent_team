"""B-2 Task 3: BotTurnTracker — cap consecutive bot-to-bot turns per chat."""
import threading

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


def test_claim_message_dedups_same_message_id_across_bots():
    t = BotTurnTracker()
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="42") is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="42") is False


def test_claim_message_processes_different_message_ids():
    t = BotTurnTracker()
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="42") is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="43") is True


def test_claim_message_empty_ids_keep_legacy_per_bot_behavior():
    t = BotTurnTracker()
    assert t.claim_message(channel="telegram", chat_id=-100, message_id=None) is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id=None) is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="") is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="") is True


def test_claim_message_scoped_by_chat_to_avoid_cross_chat_collisions():
    t = BotTurnTracker()
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="42") is True
    assert t.claim_message(channel="telegram", chat_id=-200, message_id="42") is True


def test_claim_message_evicts_oldest_seen_message_id():
    t = BotTurnTracker(max_seen_message_ids=2)
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="1") is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="2") is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="3") is True
    assert t.claim_message(channel="telegram", chat_id=-100, message_id="1") is True


def test_claim_message_concurrent_same_message_id_only_one_wins():
    t = BotTurnTracker()
    barrier = threading.Barrier(2)
    results: list[bool] = []
    result_lock = threading.Lock()

    def claim() -> None:
        barrier.wait()
        claimed = t.claim_message(channel="telegram", chat_id=-100, message_id="42")
        with result_lock:
            results.append(claimed)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]
