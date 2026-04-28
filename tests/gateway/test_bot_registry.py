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
