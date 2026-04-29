"""B-2 Task 6: Telegram policy gate covering privacy / auth / bot-policy / cap."""
from src.channels.base import InboundMessage
from src.channels.telegram_runner import _should_handle
from src.core.bots import BotConfig
from src.gateway.bot_turns import BotTurnTracker


def _make_bot_cfg(**overrides):
    base = dict(
        id="dev",
        channel="telegram",
        token_env="BOT_DEV_TOKEN",
        default_runner="claude",
        allow_bot_messages="off",
        allow_all_groups=False,
        allowed_chat_ids=None,
    )
    base.update(overrides)
    return BotConfig(**base)


def _make_msg(**overrides):
    base = dict(
        user_id=1, channel="telegram", text="hi", message_id="1",
        bot_id="dev", chat_id=-100, chat_type="supergroup",
        mentioned_bot_ids=[], from_bot=False,
    )
    base.update(overrides)
    return InboundMessage(**base)


# ─── DMs always pass ───────────────────────────────────────────────────

def test_dm_always_handled_even_without_mention():
    cfg = _make_bot_cfg()
    msg = _make_msg(chat_id=1, chat_type="private", mentioned_bot_ids=[])
    assert _should_handle(msg, cfg, turns=None) is True


def test_dm_handled_when_from_bot_off_policy():
    """DMs from another bot are still passed through; gate applies only to groups."""
    cfg = _make_bot_cfg(allow_bot_messages="off")
    msg = _make_msg(chat_id=1, chat_type="private", from_bot=True)
    assert _should_handle(msg, cfg, turns=None) is True


# ─── Group authorisation ───────────────────────────────────────────────

def test_group_drops_when_not_authorised():
    cfg = _make_bot_cfg(allow_all_groups=False, allowed_chat_ids=[-200])
    msg = _make_msg(chat_id=-100, mentioned_bot_ids=["dev"])
    assert _should_handle(msg, cfg, turns=None) is False


def test_group_allowed_when_chat_id_in_allowlist():
    cfg = _make_bot_cfg(allow_all_groups=False, allowed_chat_ids=[-100])
    msg = _make_msg(chat_id=-100, mentioned_bot_ids=["dev"])
    assert _should_handle(msg, cfg, turns=None) is True


def test_group_allowed_when_allow_all_groups_true():
    cfg = _make_bot_cfg(allow_all_groups=True, allowed_chat_ids=None)
    msg = _make_msg(chat_id=-100, mentioned_bot_ids=["dev"])
    assert _should_handle(msg, cfg, turns=None) is True


# ─── Group + human, no mention ─────────────────────────────────────────

def test_group_drops_unmentioned_human():
    cfg = _make_bot_cfg(allow_all_groups=True)
    msg = _make_msg(mentioned_bot_ids=[], from_bot=False)
    assert _should_handle(msg, cfg, turns=None) is False


def test_group_handles_mentioned_human():
    cfg = _make_bot_cfg(allow_all_groups=True)
    msg = _make_msg(mentioned_bot_ids=["dev"], from_bot=False)
    assert _should_handle(msg, cfg, turns=None) is True


def test_group_drops_human_mentioning_other_bot_only():
    """Same chat, other bot mentioned but not us → ignore."""
    cfg = _make_bot_cfg(allow_all_groups=True)
    msg = _make_msg(mentioned_bot_ids=["search"], from_bot=False)
    assert _should_handle(msg, cfg, turns=None) is False


# ─── Group + bot, varying allow_bot_messages ──────────────────────────

def test_group_drops_bot_when_policy_off():
    cfg = _make_bot_cfg(allow_all_groups=True, allow_bot_messages="off")
    msg = _make_msg(mentioned_bot_ids=["dev"], from_bot=True)
    assert _should_handle(msg, cfg, turns=None) is False


def test_group_handles_bot_when_policy_mentions_and_mentioned():
    cfg = _make_bot_cfg(allow_all_groups=True, allow_bot_messages="mentions")
    msg = _make_msg(mentioned_bot_ids=["dev"], from_bot=True)
    assert _should_handle(msg, cfg, turns=None) is True


def test_group_drops_bot_when_policy_mentions_but_not_mentioned():
    cfg = _make_bot_cfg(allow_all_groups=True, allow_bot_messages="mentions")
    msg = _make_msg(mentioned_bot_ids=["search"], from_bot=True)
    assert _should_handle(msg, cfg, turns=None) is False


def test_group_handles_bot_when_policy_all_even_without_mention():
    cfg = _make_bot_cfg(allow_all_groups=True, allow_bot_messages="all")
    msg = _make_msg(mentioned_bot_ids=[], from_bot=True)
    assert _should_handle(msg, cfg, turns=None) is True


# ─── Turn cap ──────────────────────────────────────────────────────────

def test_turn_cap_blocks_bot_message_at_threshold():
    cfg = _make_bot_cfg(allow_all_groups=True, allow_bot_messages="all")
    turns = BotTurnTracker(cap=2)
    turns.note_bot_turn(channel="telegram", chat_id=-100)
    turns.note_bot_turn(channel="telegram", chat_id=-100)
    msg = _make_msg(mentioned_bot_ids=["dev"], from_bot=True)
    assert _should_handle(msg, cfg, turns=turns) is False


def test_turn_cap_allows_bot_message_just_below_threshold():
    cfg = _make_bot_cfg(allow_all_groups=True, allow_bot_messages="all")
    turns = BotTurnTracker(cap=3)
    turns.note_bot_turn(channel="telegram", chat_id=-100)
    turns.note_bot_turn(channel="telegram", chat_id=-100)
    msg = _make_msg(mentioned_bot_ids=["dev"], from_bot=True)
    assert _should_handle(msg, cfg, turns=turns) is True


def test_turn_cap_does_not_apply_to_human_messages():
    """Human message in capped chat: still handled (and resets counter elsewhere)."""
    cfg = _make_bot_cfg(allow_all_groups=True)
    turns = BotTurnTracker(cap=1)
    turns.note_bot_turn(channel="telegram", chat_id=-100)
    msg = _make_msg(mentioned_bot_ids=["dev"], from_bot=False)
    assert _should_handle(msg, cfg, turns=turns) is True


def test_turn_cap_does_not_apply_in_dm():
    """DMs are unaffected even if cap_reached."""
    cfg = _make_bot_cfg(allow_bot_messages="all")
    turns = BotTurnTracker(cap=1)
    turns.note_bot_turn(channel="telegram", chat_id=1)
    msg = _make_msg(chat_id=1, chat_type="private", from_bot=True)
    assert _should_handle(msg, cfg, turns=turns) is True
