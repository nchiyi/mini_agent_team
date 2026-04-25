# tests/gateway/test_router_modules.py
import pytest
from src.gateway.router import Router, ParsedCommand
from src.skills.loader import ModuleRegistry, LoadedModule
from src.skills.manifest import ModuleManifest


def _make_registry(commands: list[str]) -> ModuleRegistry:
    async def h(*a):
        yield "x"

    reg = ModuleRegistry()
    reg.register(LoadedModule(
        manifest=ModuleManifest(name="testmod", version="1.0", commands=commands,
                                description="", dependencies=[], enabled=True, timeout_seconds=5),
        handler=h,
    ))
    return reg


@pytest.mark.asyncio
async def test_module_command_parsed_as_is_module():
    reg = _make_registry(["/search"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = await router.parse("/search dogs")
    assert cmd.is_module is True
    assert cmd.module_command == "/search"
    assert cmd.prompt == "dogs"


@pytest.mark.asyncio
async def test_module_command_no_args():
    reg = _make_registry(["/search"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = await router.parse("/search")
    assert cmd.is_module is True
    assert cmd.module_command == "/search"
    assert cmd.prompt == ""


@pytest.mark.asyncio
async def test_builtin_cancel_not_shadowed_by_module():
    reg = _make_registry(["/cancel"])  # module tries to claim /cancel
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = await router.parse("/cancel")
    # builtins have priority
    assert cmd.is_cancel is True
    assert cmd.is_module is False


@pytest.mark.asyncio
async def test_runner_prefix_not_shadowed_by_module():
    reg = _make_registry(["/claude"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = await router.parse("/claude hello")
    # runner prefix has priority over module
    assert cmd.is_module is False
    assert cmd.runner == "claude"
    assert cmd.prompt == "hello"


@pytest.mark.asyncio
async def test_no_module_registry_unknown_slash_falls_to_default():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("/unknown hello")
    assert cmd.is_module is False
    assert cmd.runner == "claude"
    assert cmd.prompt == "/unknown hello"


@pytest.mark.asyncio
async def test_module_registry_none_is_ignored():
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=None)
    cmd = await router.parse("/search dogs")
    assert cmd.is_module is False


@pytest.mark.asyncio
async def test_plain_text_still_routes_to_default():
    reg = _make_registry(["/search"])
    router = Router(known_runners={"claude"}, default_runner="claude", module_registry=reg)
    cmd = await router.parse("hello world")
    assert cmd.is_module is False
    assert cmd.runner == "claude"
