# src/gateway/dispatcher.py
"""
Channel-agnostic dispatch logic.

Entry point: dispatch(inbound, bridge, ctx)

All private _dispatch_* helpers, role prompt injection, and memory distillation
live here; main.py is left with bootstrap/startup only.
"""
import asyncio
import contextlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from src.channels.base import InboundMessage
from src.core.memory.context import ContextAssembler
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store
from src.gateway.app_context import AppContext
from src.gateway.file_resolver import resolve_file_refs
from src.gateway.nlu import FastPathDetector
from src.gateway.rate_limit import RateLimiter
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.gateway.streaming import StreamingBridge
from src.roles import build_role_prompt_prefix
from src.skills.loader import SkillRegistry

if TYPE_CHECKING:
    from src.core.config import Config

logger = logging.getLogger(__name__)

_DEFAULT_ROLE = "department-head"
_role_prompt_cache: dict[str, tuple[float, str]] = {}


def apply_role_prompt(prompt: str, role_slug: str, base_dir: str) -> str:
    role_file = Path(base_dir) / "roster" / f"{role_slug}.md"
    try:
        mtime = role_file.stat().st_mtime
    except OSError:
        mtime = 0.0
    cached = _role_prompt_cache.get(role_slug)
    if cached is None or cached[0] != mtime:
        prefix = build_role_prompt_prefix(role_slug, base_dir)
        _role_prompt_cache[role_slug] = (mtime, prefix)
    else:
        prefix = cached[1]
    return prefix + prompt if prefix else prompt


async def maybe_distill(
    *,
    user_id: int,
    channel: str,
    tier1: Tier1Store,
    tier3: Tier3Store,
    runners: dict,
    cfg: "Config",
) -> None:
    trigger = cfg.memory.distill_trigger_turns
    count = await tier3.count_turns(user_id=user_id, channel=channel)
    if count <= trigger:
        return

    last_ts = await tier3.get_last_distill_ts(user_id=user_id, channel=channel)
    now = datetime.now(timezone.utc)
    if last_ts is not None and (now - last_ts) < timedelta(minutes=30):
        return

    to_summarise = count - trigger
    oldest = await tier3.get_oldest_turns(user_id=user_id, channel=channel, n=to_summarise)
    if not oldest:
        return

    transcript = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in oldest)
    summary_prompt = (
        "Summarise the following conversation turns into a concise paragraph "
        "that preserves key facts, decisions, and context. "
        "Write in third person. Be brief.\n\n" + transcript
    )

    default_runner = runners.get(cfg.gateway.default_runner)
    if default_runner is None:
        logger.warning("maybe_distill: default runner not found, skipping")
        return

    try:
        chunks: list[str] = []
        async for chunk in default_runner.run(
            prompt=summary_prompt, user_id=user_id, channel=channel, cwd="."
        ):
            chunks.append(chunk)
        summary = "".join(chunks).strip()
    except Exception:
        logger.error("maybe_distill: summarisation failed", exc_info=True)
        return

    if summary:
        tier1.remember(user_id=user_id, channel=channel,
                       content=f"[session_summary] {summary}")

    last_id = oldest[-1]["id"]
    pruned = await tier3.prune_before_id(user_id=user_id, channel=channel, before_id=last_id)
    await tier3.set_last_distill_ts(user_id=user_id, channel=channel, ts=now)
    logger.info("Distilled %d turns into Tier1 for user=%s channel=%s", pruned, user_id, channel)


async def _dispatch_pipeline(
    *,
    inbound: InboundMessage,
    session,
    runners: dict,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    recent_turns: int,
    send_reply,
    pipeline_runners: list[str],
    prompt: str,
    max_rounds: int = 4,
    token_budget: int = 0,
) -> None:
    await tier3.save_turn(
        user_id=inbound.user_id, channel=inbound.channel,
        role="user", content=inbound.text,
    )
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel, recent_turns=recent_turns
    )
    role_prompt = apply_role_prompt(prompt, session.active_role, session.cwd)
    current_input = (context + "\n\n" + role_prompt) if context else role_prompt
    full_log: list[str] = []
    consumed_tokens = 0

    capped_runners = pipeline_runners[:max_rounds]
    for i, runner_name in enumerate(capped_runners):
        if token_budget > 0 and consumed_tokens >= token_budget:
            await send_reply(
                f"⚠️ 已達 token budget 上限（{consumed_tokens:,}/{token_budget:,}），"
                f"pipeline 提前結束於第 {i} 輪。"
            )
            break

        runner = runners.get(runner_name)
        if not runner:
            await send_reply(f"Runner '{runner_name}' not found, skipping.")
            continue

        label = f"[{runner_name.upper()} {'→' * (i + 1)}]"
        await send_reply(f"{label} processing...")

        if i > 0:
            current_input = (
                f"Original request: {prompt}\n\n"
                f"Previous response ({capped_runners[i - 1]}):\n{current_input}\n\n"
                f"Please review, improve, or continue based on the above:"
            )

        chunks: list[str] = []
        try:
            from src.core.memory.context import count_tokens as _ct
            _pt = _ct(current_input)
            async for chunk in runner.run(
                prompt=current_input,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
            ):
                chunks.append(chunk)
            output = "".join(chunks).strip()
            _ct_out = _ct(output)
            await tier3.log_usage(
                user_id=inbound.user_id, channel=inbound.channel, runner=runner_name,
                prompt_tokens=_pt, completion_tokens=_ct_out,
            )
            consumed_tokens += _pt + _ct_out
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
    inbound: InboundMessage,
    session,
    runners: dict,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    recent_turns: int,
    send_reply,
    discussion_runners: list[str],
    discussion_rounds: int,
    prompt: str,
    token_budget: int = 0,
) -> None:
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="user", content=inbound.text)
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel, recent_turns=recent_turns
    )
    role_prompt = apply_role_prompt(prompt, session.active_role, session.cwd)
    prompt = (context + "\n\n" + role_prompt) if context else role_prompt
    history: list[tuple[str, str]] = []
    consumed_tokens = 0

    for round_num in range(discussion_rounds):
        if token_budget > 0 and consumed_tokens >= token_budget:
            await send_reply(
                f"⚠️ 已達 token budget 上限（{consumed_tokens:,}/{token_budget:,}），"
                f"討論提前結束於第 {round_num} 輪。"
            )
            break

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
            from src.core.memory.context import count_tokens as _ct
            _pt = _ct(round_prompt)
            async for chunk in runner.run(
                prompt=round_prompt, user_id=inbound.user_id,
                channel=inbound.channel, cwd=session.cwd,
            ):
                chunks.append(chunk)
            output = "".join(chunks).strip()
            _ct_out = _ct(output)
            await tier3.log_usage(
                user_id=inbound.user_id, channel=inbound.channel, runner=runner_name,
                prompt_tokens=_pt, completion_tokens=_ct_out,
            )
            consumed_tokens += _pt + _ct_out
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
    inbound: InboundMessage,
    session,
    runners: dict,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    recent_turns: int,
    send_reply,
    debate_runners: list[str],
    prompt: str,
    max_voters: int = 5,
) -> None:
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="user", content=inbound.text)
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel, recent_turns=recent_turns
    )
    role_prompt = apply_role_prompt(prompt, session.active_role, session.cwd)
    prompt = (context + "\n\n" + role_prompt) if context else role_prompt
    debate_runners = debate_runners[:max_voters]
    await send_reply(f"[DEBATE] {' vs '.join(r.upper() for r in debate_runners)}")

    from src.core.memory.context import count_tokens as _ct
    _debate_pt = _ct(prompt)

    answers = dict(await asyncio.gather(*[
        _get_runner_response(r, prompt, inbound, session, runners)
        for r in debate_runners
    ]))
    labels = {r: chr(65 + i) for i, r in enumerate(debate_runners)}

    for runner_name in debate_runners:
        label = labels[runner_name]
        await send_reply(f"[{label}] {runner_name.upper()}\n{answers[runner_name]}")
        await tier3.log_usage(
            user_id=inbound.user_id, channel=inbound.channel, runner=runner_name,
            prompt_tokens=_debate_pt, completion_tokens=_ct(answers[runner_name]),
        )

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


async def _dispatch_single_runner(
    inbound: InboundMessage,
    session,
    runners: dict,
    bridge: StreamingBridge,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    send_reply,
    recent_turns: int,
    role_slug: str,
    cmd,
    cfg: "Config | None" = None,
    tier1: "Tier1Store | None" = None,
) -> None:
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
    resolved_prompt = await resolve_file_refs(cmd.prompt, session.cwd)
    # Pass empty string to get only the prefix (reuses _role_prompt_cache)
    role_prefix = apply_role_prompt("", role_slug, session.cwd)
    user_message = (context + "\n\n" + resolved_prompt) if context else resolved_prompt

    from src.core.memory.context import count_tokens
    prompt_tokens = count_tokens((role_prefix + user_message) if role_prefix else user_message)

    try:
        response_chunks: list[str] = []

        async def collecting_gen():
            async for chunk in target_runner.run(
                prompt=user_message,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
                attachments=inbound.attachments or None,
                role_prefix=role_prefix,
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
            completion_tokens = count_tokens(response)
            await tier3.log_usage(
                user_id=inbound.user_id, channel=inbound.channel,
                runner=session.current_runner,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            )
            if cfg and tier1:
                await maybe_distill(user_id=inbound.user_id, channel=inbound.channel,
                                    tier1=tier1, tier3=tier3, runners=runners, cfg=cfg)
    except TimeoutError:
        await send_reply("Runner timed out.")
    except Exception as e:
        logger.error("Runner error: %s", e, exc_info=True)
        await send_reply("An error occurred. Please try again.")


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
    module_registry: "SkillRegistry | None" = None,
    cfg: "Config | None" = None,
    nlu_detector: "FastPathDetector | None" = None,
    rate_limiter: "RateLimiter | None" = None,
) -> None:
    """Channel-agnostic gateway logic."""
    if rate_limiter is not None and not rate_limiter.check(inbound.user_id):
        await send_reply("⏱ 訊息頻率過高，請稍後再試。")
        return
    await session_mgr.restore_settings_if_needed(inbound.user_id, inbound.channel)
    session = session_mgr.get_or_create(user_id=inbound.user_id, channel=inbound.channel)
    cmd = await router.parse(inbound.text)
    active_role = session_mgr.get_active_role(inbound.user_id, inbound.channel)
    if active_role:
        session.active_role = active_role
    role_slug = session.active_role or cmd.role or _DEFAULT_ROLE

    if not inbound.text.startswith("/") and not any([
        cmd.is_pipeline, cmd.is_discussion, cmd.is_debate,
    ]):
        _detector = nlu_detector or FastPathDetector(set(runners.keys()))
        nlu_cmd = _detector.detect(inbound.text)
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
    if cmd.is_voice_on:
        session_mgr.set_voice_enabled(inbound.user_id, inbound.channel, True)
        await send_reply("Voice replies enabled. Send a voice message or text to try.")
        return
    if cmd.is_voice_off:
        session_mgr.set_voice_enabled(inbound.user_id, inbound.channel, False)
        await send_reply("Voice replies disabled.")
        return
    if cmd.is_usage:
        from datetime import datetime, timezone, timedelta
        summary = await tier3.get_usage_summary(user_id=inbound.user_id)
        now = datetime.now(timezone.utc)
        today_iso = now.strftime("%Y-%m-%d")
        week_ago_iso = (now - timedelta(days=7)).isoformat()
        tokens_today = await tier3.get_token_usage_since(user_id=inbound.user_id, since_iso=today_iso)
        tokens_week = await tier3.get_token_usage_since(user_id=inbound.user_id, since_iso=week_ago_iso)

        rl_cfg = cfg.gateway.rate_limit if cfg else None
        daily_budget = rl_cfg.daily_token_budget if rl_cfg else 0
        weekly_budget = rl_cfg.weekly_token_budget if rl_cfg else 0

        def _budget_line(used: int, budget: int, label: str) -> str:
            if budget > 0:
                pct = used / budget * 100
                remaining = max(budget - used, 0)
                return f"{label}：{used:,} / {budget:,} tokens ({pct:.1f}%)，剩餘 {remaining:,}"
            return f"{label}：{used:,} tokens（無上限）"

        lines = [
            _budget_line(tokens_today, daily_budget, "今日"),
            _budget_line(tokens_week, weekly_budget, "近 7 天"),
            "",
            "各 Runner 累計：",
        ]
        grand_total = 0
        for runner_name, stats in (summary or {}).items():
            lines.append(
                f"  {runner_name}: {stats['prompt']:,} prompt + "
                f"{stats['completion']:,} completion = {stats['total']:,} total"
            )
            grand_total += stats["total"]
        if grand_total:
            lines.append(f"總計：{grand_total:,} tokens")
        else:
            lines.append("（尚無記錄）")
        await send_reply("\n".join(lines))
        return
    if cmd.is_status:
        mod_names = module_registry.get_names() if module_registry else []
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
        auth_mode = getattr(cfg, "allow_all_users", None)
        auth_desc = "open" if auth_mode else "strict allowlist"
        await send_reply(
            f"Runner: {session.current_runner}\n"
            f"Context: {context_tokens}/{token_budget} tokens\n"
            f"Turns: {len(turns)}\n"
            f"Modules: {mod_names or '(none)'}\n"
            f"Role: {session.active_role or '(none)'}\n"
            f"CWD: {session.cwd}\n"
            f"Auth: {auth_desc}"
        )
        return
    if cmd.is_switch_runner:
        session.current_runner = cmd.runner
        await send_reply(f"Switched to {cmd.runner}")
        return

    # Daily token budget warning check
    if cfg and cfg.gateway.rate_limit.daily_token_budget > 0:
        from datetime import datetime, timezone as _tz
        _today_iso = datetime.now(_tz.utc).strftime("%Y-%m-%d")
        _tokens_today = await tier3.get_token_usage_since(
            user_id=inbound.user_id, since_iso=_today_iso
        )
        _daily_budget = cfg.gateway.rate_limit.daily_token_budget
        _warn_threshold = cfg.gateway.rate_limit.warn_threshold
        _usage_ratio = _tokens_today / _daily_budget
        if _usage_ratio >= 1.0:
            await send_reply(
                f"⛔ 今日 token 已用盡（{_tokens_today:,} / {_daily_budget:,}）。"
                f"如需繼續請明日再試。"
            )
            return
        if _usage_ratio >= _warn_threshold:
            await send_reply(
                f"⚠️ 今日已使用 {_usage_ratio * 100:.0f}% token budget"
                f"（{_tokens_today:,} / {_daily_budget:,}）。"
            )

    _sem = rate_limiter.semaphore if rate_limiter is not None else contextlib.nullcontext()
    async with _sem:
        if cmd.is_module and module_registry:
            await bridge.stream(
                user_id=inbound.user_id,
                chunks=module_registry.dispatch(
                    cmd.module_command, cmd.prompt, inbound.user_id, inbound.channel
                ),
            )
            return

        if cmd.is_pipeline:
            _pipe_runner_obj = runners.get(session.current_runner)
            _pipe_budget = _pipe_runner_obj.context_token_budget if (_pipe_runner_obj and cfg and cfg.dispatch.enforce_token_budget) else 0
            await _dispatch_pipeline(
                inbound=inbound, session=session, runners=runners,
                tier3=tier3, assembler=assembler, recent_turns=recent_turns, send_reply=send_reply,
                pipeline_runners=cmd.pipeline_runners, prompt=cmd.prompt,
                max_rounds=cfg.dispatch.max_pipeline_rounds if cfg else 4,
                token_budget=_pipe_budget,
            )
            if cfg:
                await maybe_distill(user_id=inbound.user_id, channel=inbound.channel,
                                    tier1=tier1, tier3=tier3, runners=runners, cfg=cfg)
            return

        if cmd.is_discussion:
            _disc_runner_obj = runners.get(session.current_runner)
            _disc_budget = _disc_runner_obj.context_token_budget if _disc_runner_obj else 0
            await _dispatch_discussion(
                inbound=inbound, session=session, runners=runners,
                tier3=tier3, assembler=assembler, recent_turns=recent_turns, send_reply=send_reply,
                discussion_runners=cmd.discussion_runners,
                discussion_rounds=cmd.discussion_rounds,
                prompt=cmd.prompt,
                token_budget=_disc_budget,
            )
            if cfg:
                await maybe_distill(user_id=inbound.user_id, channel=inbound.channel,
                                    tier1=tier1, tier3=tier3, runners=runners, cfg=cfg)
            return

        if cmd.is_debate:
            await _dispatch_debate(
                inbound=inbound, session=session, runners=runners,
                tier3=tier3, assembler=assembler, recent_turns=recent_turns, send_reply=send_reply,
                debate_runners=cmd.debate_runners, prompt=cmd.prompt,
                max_voters=cfg.dispatch.max_debate_voters if cfg else 5,
            )
            if cfg:
                await maybe_distill(user_id=inbound.user_id, channel=inbound.channel,
                                    tier1=tier1, tier3=tier3, runners=runners, cfg=cfg)
            return

        await _dispatch_single_runner(
            inbound=inbound, session=session, runners=runners,
            bridge=bridge, tier3=tier3, assembler=assembler,
            send_reply=send_reply, recent_turns=recent_turns,
            role_slug=role_slug, cmd=cmd, cfg=cfg, tier1=tier1,
        )
