# main.py
"""
Gateway Agent Platform — entry point.
Runs TelegramAdapter and/or DiscordAdapter concurrently via asyncio.gather().
Includes Tier 1 permanent memory, Tier 3 SQLite history, and context assembly.
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.core.config import load_config, Config
from src.runners.audit import AuditLog
from src.runners.cli_runner import CLIRunner
from src.channels.telegram import TelegramAdapter
from src.channels.discord_adapter import DiscordAdapter
from src.channels.base import InboundMessage, BaseAdapter
from src.gateway.router import Router
from src.gateway.session import SessionManager, get_active_role
from src.gateway.streaming import StreamingBridge
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store
from src.core.memory.context import ContextAssembler
from src.modules.loader import ModuleRegistry, load_modules
from src.gateway.nlu import FastPathDetector
from src.roles import build_role_prompt_prefix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")


def _apply_role_prompt(prompt: str, role_slug: str, base_dir: str) -> str:
    prefix = build_role_prompt_prefix(role_slug, base_dir)
    return prefix + prompt if prefix else prompt



def _build_shared(cfg: Config, audit: AuditLog):
    runners = {
        name: CLIRunner(
            name=name,
            binary=rc.path,
            args=rc.args,
            timeout_seconds=rc.timeout_seconds,
            context_token_budget=rc.context_token_budget,
            audit=audit,
        )
        for name, rc in cfg.runners.items()
    }
    module_registry = load_modules(cfg.modules_dir)
    router = Router(
        known_runners=set(runners.keys()),
        default_runner=cfg.gateway.default_runner,
        module_registry=module_registry,
    )
    session_mgr = SessionManager(
        idle_minutes=cfg.gateway.session_idle_minutes,
        default_runner=cfg.gateway.default_runner,
        default_cwd=cfg.default_cwd,
    )
    tier1 = Tier1Store(permanent_dir=cfg.memory.cold_permanent_path)
    tier3 = Tier3Store(db_path=cfg.memory.db_path)
    default_runner_cfg = cfg.runners.get(cfg.gateway.default_runner)
    max_tokens = default_runner_cfg.context_token_budget if default_runner_cfg else 4000
    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=max_tokens)
    return runners, module_registry, router, session_mgr, tier1, tier3, assembler


async def _dispatch_pipeline(
    *,
    inbound: "InboundMessage",
    session,
    runners: dict,
    tier3: "Tier3Store",
    assembler: ContextAssembler,
    recent_turns: int,
    send_reply,
    pipeline_runners: list[str],
    prompt: str,
) -> None:
    """Run prompt through a chain of runners; each step receives the previous output."""
    await tier3.save_turn(
        user_id=inbound.user_id, channel=inbound.channel,
        role="user", content=inbound.text,
    )
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel, recent_turns=recent_turns
    )
    role_prompt = _apply_role_prompt(prompt, session.active_role, session.cwd)
    current_input = (context + "\n\n" + role_prompt) if context else role_prompt
    full_log: list[str] = []

    for i, runner_name in enumerate(pipeline_runners):
        runner = runners.get(runner_name)
        if not runner:
            await send_reply(f"Runner '{runner_name}' not found, skipping.")
            continue

        label = f"[{runner_name.upper()} {'→' * (i + 1)}]"
        await send_reply(f"{label} processing...")

        if i > 0:
            current_input = (
                f"Original request: {prompt}\n\n"
                f"Previous response ({pipeline_runners[i - 1]}):\n{current_input}\n\n"
                f"Please review, improve, or continue based on the above:"
            )

        chunks: list[str] = []
        try:
            async for chunk in runner.run(
                prompt=current_input,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
            ):
                chunks.append(chunk)
            output = "".join(chunks).strip()
        except TimeoutError:
            await send_reply(f"{label} timed out.")
            break
        except Exception as e:
            logger.error("Pipeline runner %s error: %s", runner_name, e, exc_info=True)
            await send_reply(f"{label} error — stopping pipeline.")
            break

        await send_reply(f"{label}\n{output}")
        full_log.append(f"{runner_name}: {output}")
        current_input = output

    if full_log:
        combined = " | ".join(pipeline_runners) + " pipeline:\n" + "\n\n---\n".join(full_log)
        await tier3.save_turn(
            user_id=inbound.user_id, channel=inbound.channel,
            role="assistant", content=combined,
        )


async def _dispatch_discussion(
    *,
    inbound: "InboundMessage",
    session,
    runners: dict,
    tier3: "Tier3Store",
    assembler: ContextAssembler,
    recent_turns: int,
    send_reply,
    discussion_runners: list[str],
    discussion_rounds: int,
    prompt: str,
) -> None:
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="user", content=inbound.text)
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel, recent_turns=recent_turns
    )
    role_prompt = _apply_role_prompt(prompt, session.active_role, session.cwd)
    prompt = (context + "\n\n" + role_prompt) if context else role_prompt
    history: list[tuple[str, str]] = []

    for round_num in range(discussion_rounds):
        runner_name = discussion_runners[round_num % len(discussion_runners)]
        runner = runners.get(runner_name)
        if not runner:
            await send_reply(f"Runner '{runner_name}' not found.")
            continue

        label = f"[Round {round_num + 1} — {runner_name.upper()}]"
        await send_reply(f"{label} thinking...")

        if not history:
            round_prompt = prompt
        else:
            history_text = "\n\n".join(f"{name.upper()}: {resp}" for name, resp in history)
            round_prompt = (
                f"Original question: {prompt}\n\n"
                f"Discussion so far:\n{history_text}\n\n"
                f"Your turn ({runner_name}): Please respond, critique, or build on the above."
            )

        chunks: list[str] = []
        try:
            async for chunk in runner.run(
                prompt=round_prompt, user_id=inbound.user_id,
                channel=inbound.channel, cwd=session.cwd,
            ):
                chunks.append(chunk)
            output = "".join(chunks).strip()
        except (TimeoutError, Exception) as e:
            logger.error("Discussion round %d error: %s", round_num + 1, e, exc_info=True)
            await send_reply(f"{label} error — stopping discussion.")
            break

        await send_reply(f"{label}\n{output}")
        history.append((runner_name, output))

    if len(history) >= 2:
        synthesiser = discussion_runners[-1]
        synth_runner = runners.get(synthesiser)
        if synth_runner:
            await send_reply(f"[SYNTHESIS — {synthesiser.upper()}] summarising...")
            history_text = "\n\n".join(f"{n.upper()}: {r}" for n, r in history)
            synth_prompt = (
                f"Original question: {prompt}\n\n"
                f"Full discussion:\n{history_text}\n\n"
                f"Please synthesise the key conclusions and actionable takeaways."
            )
            synth_chunks: list[str] = []
            async for chunk in synth_runner.run(
                prompt=synth_prompt, user_id=inbound.user_id,
                channel=inbound.channel, cwd=session.cwd,
            ):
                synth_chunks.append(chunk)
            synthesis = "".join(synth_chunks).strip()
            await send_reply(f"[CONCLUSION]\n{synthesis}")
            history.append((synthesiser + "_synthesis", synthesis))

    if history:
        transcript = "\n\n---\n".join(f"{n}: {r}" for n, r in history)
        await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                              role="assistant", content=f"[discussion] {transcript}")


async def _get_runner_response(runner_name: str, prompt: str, inbound, session, runners) -> tuple[str, str]:
    runner = runners.get(runner_name)
    if not runner:
        return runner_name, "(runner not found)"
    chunks: list[str] = []
    try:
        async for chunk in runner.run(
            prompt=prompt, user_id=inbound.user_id,
            channel=inbound.channel, cwd=session.cwd,
        ):
            chunks.append(chunk)
        return runner_name, "".join(chunks).strip()
    except Exception as e:
        logger.error("Debate runner %s error: %s", runner_name, e, exc_info=True)
        return runner_name, f"(error: {e})"


async def _dispatch_debate(
    *,
    inbound: "InboundMessage",
    session,
    runners: dict,
    tier3: "Tier3Store",
    assembler: ContextAssembler,
    recent_turns: int,
    send_reply,
    debate_runners: list[str],
    prompt: str,
) -> None:
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="user", content=inbound.text)
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel, recent_turns=recent_turns
    )
    role_prompt = _apply_role_prompt(prompt, session.active_role, session.cwd)
    prompt = (context + "\n\n" + role_prompt) if context else role_prompt
    await send_reply(f"[DEBATE] {' vs '.join(r.upper() for r in debate_runners)}")

    answers = dict(await asyncio.gather(*[
        _get_runner_response(r, prompt, inbound, session, runners)
        for r in debate_runners
    ]))
    labels = {r: chr(65 + i) for i, r in enumerate(debate_runners)}

    for runner_name in debate_runners:
        label = labels[runner_name]
        await send_reply(f"[{label}] {runner_name.upper()}\n{answers[runner_name]}")

    vote_prompt_template = (
        f"Original question: {prompt}\n\n"
        + "\n\n".join(f"Option {labels[r]} ({r}):\n{answers[r]}" for r in debate_runners)
        + "\n\nWhich answer is the most correct, complete, and actionable? "
          "Reply with ONLY the letter on the first line, then your reasoning."
    )

    await send_reply("[VOTING] Each runner casting vote...")
    vote_results = dict(await asyncio.gather(*[
        _get_runner_response(r, vote_prompt_template, inbound, session, runners)
        for r in debate_runners
    ]))

    tally: dict[str, int] = {r: 0 for r in debate_runners}
    for voter, vote_text in vote_results.items():
        first_line = vote_text.strip().split("\n")[0].strip().upper()
        for runner_name, label in labels.items():
            if first_line == label:
                tally[runner_name] += 1
                await send_reply(f"[{voter.upper()} votes {label}] {vote_text}")
                break

    winner = max(tally, key=lambda r: tally[r])
    await send_reply(
        f"[RESULT] Winner: {winner.upper()} "
        f"({tally[winner]}/{len(debate_runners)} votes)\n\n"
        f"Winning answer:\n{answers[winner]}"
    )

    transcript = (
        f"Debate: {prompt}\n\n"
        + "\n\n".join(f"{r} [{labels[r]}]: {answers[r]}" for r in debate_runners)
        + f"\n\nWinner: {winner} ({tally[winner]} votes)"
    )
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="assistant", content=f"[debate] {transcript}")


async def dispatch(
    inbound: InboundMessage,
    bridge: StreamingBridge,
    session_mgr: SessionManager,
    router: Router,
    runners: dict,
    tier1: Tier1Store,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    send_reply,
    recent_turns: int,
    module_registry: ModuleRegistry | None = None,
) -> None:
    """Channel-agnostic gateway logic."""
    session = session_mgr.get_or_create(user_id=inbound.user_id, channel=inbound.channel)
    cmd = router.parse(inbound.text)
    active_role = get_active_role(inbound.user_id, inbound.channel)
    if active_role:
        session.active_role = active_role
    role_slug = session.active_role or cmd.role

    if not inbound.text.startswith("/") and not any([
        cmd.is_pipeline, cmd.is_discussion, cmd.is_debate,
    ]):
        nlu_cmd = FastPathDetector(set(runners.keys())).detect(inbound.text)
        if nlu_cmd is not None:
            cmd = nlu_cmd

    if cmd.is_remember:
        tier1.remember(user_id=inbound.user_id, channel=inbound.channel, content=cmd.prompt)
        await send_reply(f"Remembered: {cmd.prompt}")
        return
    if cmd.is_forget:
        removed = tier1.forget(user_id=inbound.user_id, channel=inbound.channel, keyword=cmd.prompt)
        await send_reply(f"Removed {removed} entries matching '{cmd.prompt}'")
        return
    if cmd.is_recall:
        results = await tier3.search(user_id=inbound.user_id, channel=inbound.channel, query=cmd.prompt, limit=5)
        if results:
            await send_reply("\n".join(r["content"] for r in results))
        else:
            await send_reply("Nothing found.")
        return
    if cmd.is_cancel:
        await send_reply("No active task to cancel.")
        return
    if cmd.is_reset:
        session_mgr.clear_active_role(inbound.user_id, inbound.channel)
        await send_reply("Context cleared.")
        return
    if cmd.is_new:
        session_mgr.clear_active_role(inbound.user_id, inbound.channel)
        await send_reply("New session started.")
        return
    if cmd.is_status:
        mod_names = module_registry.get_names() if module_registry else []
        # Build context to measure current token usage
        context_str = await assembler.build(
            user_id=inbound.user_id, channel=inbound.channel, recent_turns=recent_turns
        )
        from src.core.memory.context import count_tokens
        context_tokens = count_tokens(context_str) if context_str else 0
        default_runner_obj = runners.get(session.current_runner)
        token_budget = default_runner_obj.context_token_budget if default_runner_obj else 4000
        turns = await tier3.get_recent(
            user_id=inbound.user_id, channel=inbound.channel, n=recent_turns
        )
        await send_reply(
            f"Runner: {session.current_runner}\n"
            f"Context: {context_tokens}/{token_budget} tokens\n"
            f"Turns: {len(turns)}\n"
            f"Modules: {mod_names or '(none)'}\n"
            f"Role: {session.active_role or '(none)'}\n"
            f"CWD: {session.cwd}"
        )
        return
    if cmd.is_switch_runner:
        session.current_runner = cmd.runner
        await send_reply(f"Switched to {cmd.runner}")
        return

    if cmd.is_module and module_registry:
        await bridge.stream(
            user_id=inbound.user_id,
            chunks=module_registry.dispatch(
                cmd.module_command, cmd.prompt, inbound.user_id, inbound.channel
            ),
        )
        return

    if cmd.is_pipeline:
        await _dispatch_pipeline(
            inbound=inbound, session=session, runners=runners,
            tier3=tier3, assembler=assembler, recent_turns=recent_turns, send_reply=send_reply,
            pipeline_runners=cmd.pipeline_runners, prompt=cmd.prompt,
        )
        return

    if cmd.is_discussion:
        await _dispatch_discussion(
            inbound=inbound, session=session, runners=runners,
            tier3=tier3, assembler=assembler, recent_turns=recent_turns, send_reply=send_reply,
            discussion_runners=cmd.discussion_runners,
            discussion_rounds=cmd.discussion_rounds,
            prompt=cmd.prompt,
        )
        return

    if cmd.is_debate:
        await _dispatch_debate(
            inbound=inbound, session=session, runners=runners,
            tier3=tier3, assembler=assembler, recent_turns=recent_turns, send_reply=send_reply,
            debate_runners=cmd.debate_runners, prompt=cmd.prompt,
        )
        return

    explicit_runner = False
    if inbound.text.startswith("/"):
        prefix = inbound.text.split(None, 1)[0].lstrip("/").lower()
        explicit_runner = prefix in runners

    target_runner = runners.get(cmd.runner if explicit_runner else session.current_runner)
    if not target_runner:
        await send_reply(f"Runner '{session.current_runner}' not found.")
        return

    await tier3.save_turn(
        user_id=inbound.user_id, channel=inbound.channel,
        role="user", content=inbound.text,
    )
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel,
        recent_turns=recent_turns,
    )
    prompt = _apply_role_prompt(cmd.prompt, role_slug, session.cwd)
    full_prompt = (context + "\n\n" + prompt) if context else prompt

    try:
        response_chunks: list[str] = []

        async def collecting_gen():
            async for chunk in target_runner.run(
                prompt=full_prompt,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
            ):
                response_chunks.append(chunk)
                yield chunk

        await bridge.stream(user_id=inbound.user_id, chunks=collecting_gen())
        response = "".join(response_chunks).strip()
        if response:
            await tier3.save_turn(
                user_id=inbound.user_id, channel=inbound.channel,
                role="assistant", content=response,
            )
    except TimeoutError:
        await send_reply("Runner timed out.")
    except Exception as e:
        logger.error("Runner error: %s", e, exc_info=True)
        await send_reply("An error occurred. Please try again.")


async def run_telegram(cfg: Config, runners, module_registry, router, session_mgr,
                       tier1, tier3, assembler) -> None:
    tg_app = Application.builder().token(cfg.telegram_token).build()
    adapter = TelegramAdapter(bot=tg_app.bot, allowed_user_ids=cfg.allowed_user_ids)
    bridge = StreamingBridge(adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        inbound = InboundMessage(
            user_id=user_id,
            channel="telegram",
            text=update.message.text.strip(),
            message_id=str(update.message.message_id),
        )
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            tier1, tier3, assembler,
            lambda t: adapter.send(user_id, t),
            recent_turns=cfg.memory.tier3_context_turns,
            module_registry=module_registry,
        )

    tg_app.add_handler(MessageHandler(filters.TEXT, on_message))
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Telegram bot running")
        try:
            await asyncio.Event().wait()
        finally:
            await tg_app.updater.stop()
            await tg_app.stop()


async def run_discord(cfg: Config, runners, module_registry, router, session_mgr,
                      tier1, tier3, assembler) -> None:
    discord_bridges: dict[int, StreamingBridge] = {}

    async def gateway_handler(inbound: InboundMessage) -> None:
        if inbound.user_id not in discord_bridges:
            discord_bridges[inbound.user_id] = StreamingBridge(
                dc_adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds
            )
        bridge = discord_bridges[inbound.user_id]
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            tier1, tier3, assembler,
            lambda t: dc_adapter.send(inbound.user_id, t),
            recent_turns=cfg.memory.tier3_context_turns,
            module_registry=module_registry,
        )

    dc_adapter = DiscordAdapter(
        token=cfg.discord_token,
        allowed_user_ids=cfg.allowed_user_ids,
        gateway_handler=gateway_handler,
    )
    logger.info("Discord bot starting")
    await dc_adapter.start()


async def main(cfg_path: str = "config/config.toml", env_path: str = "secrets/.env") -> None:
    cfg = load_config(config_path=cfg_path, env_path=env_path)
    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)
    runners, module_registry, router, session_mgr, tier1, tier3, assembler = _build_shared(cfg, audit)
    await tier3.init()

    if not cfg.allowed_user_ids:
        logger.warning(
            "ALLOWED_USER_IDS is not set — bot is open to ALL users. "
            "Set ALLOWED_USER_IDS in secrets/.env to restrict access."
        )

    coroutines = []
    if cfg.telegram_token:
        coroutines.append(run_telegram(cfg, runners, module_registry, router,
                                        session_mgr, tier1, tier3, assembler))
    if cfg.discord_token:
        coroutines.append(run_discord(cfg, runners, module_registry, router,
                                       session_mgr, tier1, tier3, assembler))

    if not coroutines:
        logger.error("No tokens configured. Set TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN.")
        return

    try:
        results = await asyncio.gather(*coroutines, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Channel exited with error: %s", result, exc_info=result)
    finally:
        await tier3.close()


if __name__ == "__main__":
    asyncio.run(main())
