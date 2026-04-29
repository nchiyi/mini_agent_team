"""B-2 Task 2: BotRegistry — @username → bot_id resolution."""
from src.gateway.bot_registry import BotRegistry


def test_register_and_resolve_case_insensitive():
    reg = BotRegistry()
    reg.register(channel="telegram", username="user_DEV_bot", bot_id="dev")
    assert reg.resolve(channel="telegram", username="@user_dev_bot") == "dev"
    assert reg.resolve(channel="telegram", username="user_dev_bot") == "dev"
    assert reg.resolve(channel="telegram", username="@USER_DEV_BOT") == "dev"


def test_resolve_returns_none_for_unknown():
    reg = BotRegistry()
    assert reg.resolve(channel="telegram", username="@nope") is None


def test_resolve_returns_none_for_unknown_channel():
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    assert reg.resolve(channel="discord", username="@dev_bot") is None


def test_isolated_per_channel():
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="tg-dev")
    reg.register(channel="discord", username="dev_bot", bot_id="dc-dev")
    assert reg.resolve(channel="telegram", username="@dev_bot") == "tg-dev"
    assert reg.resolve(channel="discord", username="@dev_bot") == "dc-dev"


def test_all_returns_registered_bot_ids_for_channel():
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    reg.register(channel="telegram", username="search_bot", bot_id="search")
    reg.register(channel="discord", username="other_bot", bot_id="other")
    assert set(reg.all(channel="telegram")) == {"dev", "search"}
    assert set(reg.all(channel="discord")) == {"other"}
    assert reg.all(channel="missing") == []


def test_register_idempotent_overwrites_same_username():
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="first")
    reg.register(channel="telegram", username="dev_bot", bot_id="second")
    assert reg.resolve(channel="telegram", username="@dev_bot") == "second"
    assert set(reg.all(channel="telegram")) == {"first", "second"}


def test_concurrent_register_and_resolve_threadsafe():
    """Smoke test: hammer register/resolve from many threads, no exceptions."""
    import threading
    reg = BotRegistry()
    errors: list[Exception] = []

    def writer():
        try:
            for i in range(50):
                reg.register(channel="telegram", username=f"bot{i}", bot_id=f"id{i}")
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for i in range(50):
                reg.resolve(channel="telegram", username=f"bot{i}")
                reg.all(channel="telegram")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(2)] + \
              [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_appcontext_has_bot_registry_and_turns():
    """AppContext gains bot_registry + bot_turns fields after B-2 Task 4."""
    from src.gateway.app_context import AppContext
    fields = AppContext.__dataclass_fields__
    assert "bot_registry" in fields
    assert "bot_turns" in fields


# ─── Unicode normalisation hardening ──────────────────────────────────

def test_register_handles_fullwidth_at_sign():
    """Fullwidth ＠ (U+FF20) should NFKC-normalise to ASCII @."""
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    assert reg.resolve(channel="telegram", username="＠dev_bot") == "dev"


def test_register_handles_fullwidth_letters():
    """Fullwidth Latin letters (U+FF21-FF5A) should NFKC-fold to ASCII."""
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    assert reg.resolve(channel="telegram", username="@ｄｅｖ_ｂｏｔ") == "dev"
    assert reg.resolve(channel="telegram", username="ｄｅｖ_ｂｏｔ") == "dev"


def test_register_handles_compatibility_ligatures():
    """Ligatures like ﬁ (U+FB01) decompose under NFKC to f + i."""
    reg = BotRegistry()
    reg.register(channel="telegram", username="finder_bot", bot_id="finder")
    assert reg.resolve(channel="telegram", username="@ﬁnder_bot") == "finder"


def test_register_uses_casefold_not_lower():
    """Casefold handles edge cases lower() misses (Turkish-i, German ß)."""
    reg = BotRegistry()
    # German ß casefolds to "ss"; .lower() leaves it as ß.
    # Use a registered username that matches the casefold form.
    reg.register(channel="telegram", username="grossbot", bot_id="gross")
    assert reg.resolve(channel="telegram", username="@GROßbot") == "gross"


def test_distinct_scripts_remain_distinct():
    """NFKC doesn't cross-script-fold. Cyrillic 'е' (U+0435) is NOT Latin 'e'."""
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="latin_dev")
    # Cyrillic 'е' bot is a different identity (operator's choice to register it)
    reg.register(channel="telegram", username="dеv_bot", bot_id="cyrillic_dev")  # с looks Latin but is Cyrillic
    latin_resolved = reg.resolve(channel="telegram", username="@dev_bot")
    cyrillic_resolved = reg.resolve(channel="telegram", username="@dеv_bot")
    # They MUST resolve to their own distinct bot_ids:
    assert latin_resolved == "latin_dev"
    assert cyrillic_resolved == "cyrillic_dev"
    # Both are visible in .all()
    assert set(reg.all(channel="telegram")) == {"latin_dev", "cyrillic_dev"}


def test_normalisation_idempotent_on_already_ascii():
    """ASCII input round-trips unchanged through NFKC.casefold."""
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="dev")
    assert reg.resolve(channel="telegram", username="@dev_bot") == "dev"
    assert reg.resolve(channel="telegram", username="dev_bot") == "dev"
    assert reg.resolve(channel="telegram", username="@DEV_BOT") == "dev"


def test_register_idempotency_under_normalisation():
    """Two registrations of equivalent forms collapse to one entry."""
    reg = BotRegistry()
    reg.register(channel="telegram", username="dev_bot", bot_id="first")
    reg.register(channel="telegram", username="ＤＥＶ_ＢＯＴ", bot_id="second")  # fullwidth
    # Latest registration wins:
    assert reg.resolve(channel="telegram", username="@dev_bot") == "second"
    # Two distinct bot_ids tracked in .all() (we register'd two different bot_ids
    # against the same normalised key — both are remembered).
    assert "first" in reg.all(channel="telegram")
    assert "second" in reg.all(channel="telegram")
