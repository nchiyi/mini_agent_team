# tests/modules/test_registry.py
import pytest


def _make_registry(commands: list[str], timeout: int = 5):
    from src.modules.loader import ModuleRegistry, LoadedModule
    from src.modules.manifest import ModuleManifest

    async def handler(command, args, user_id, channel):
        yield f"result:{command}:{args}"

    manifest = ModuleManifest(
        name="test_mod", version="1.0.0", commands=commands,
        description="", dependencies=[], enabled=True, timeout_seconds=timeout,
    )
    reg = ModuleRegistry()
    reg.register(LoadedModule(manifest=manifest, handler=handler))
    return reg


async def test_registry_dispatch_calls_handler():
    reg = _make_registry(["/foo"])
    chunks = [c async for c in reg.dispatch("/foo", "bar", 1, "tg")]
    assert chunks == ["result:/foo:bar"]


async def test_registry_dispatch_unknown_command_yields_error():
    reg = _make_registry(["/foo"])
    chunks = [c async for c in reg.dispatch("/unknown", "", 1, "tg")]
    assert any("not found" in c for c in chunks)


async def test_registry_dispatch_timeout():
    import asyncio
    from src.modules.loader import ModuleRegistry, LoadedModule
    from src.modules.manifest import ModuleManifest

    async def slow_handler(command, args, user_id, channel):
        await asyncio.sleep(10)
        yield "never"

    manifest = ModuleManifest(
        name="slow", version="1.0.0", commands=["/slow"],
        description="", dependencies=[], enabled=True, timeout_seconds=1,
    )
    reg = ModuleRegistry()
    reg.register(LoadedModule(manifest=manifest, handler=slow_handler))
    chunks = [c async for c in reg.dispatch("/slow", "", 1, "tg")]
    assert any("timed out" in c for c in chunks)


def test_registry_conflict_raises():
    from src.modules.loader import ModuleRegistry, LoadedModule
    from src.modules.manifest import ModuleManifest

    async def h(*a):
        yield "x"

    def _mod(name):
        return LoadedModule(
            manifest=ModuleManifest(name=name, version="1.0", commands=["/clash"],
                                    description="", dependencies=[], enabled=True, timeout_seconds=5),
            handler=h,
        )

    reg = ModuleRegistry()
    reg.register(_mod("mod_a"))
    with pytest.raises(ValueError, match="conflict"):
        reg.register(_mod("mod_b"))


def test_registry_has_command():
    reg = _make_registry(["/ping"])
    assert reg.has_command("/ping")
    assert not reg.has_command("/pong")
