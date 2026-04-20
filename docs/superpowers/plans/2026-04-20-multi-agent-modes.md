# Multi-Agent Collaboration Modes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Add Discussion Mode and 3-Way Debate Mode to mini_agent_team, building on the existing Relay (pipeline) feature.

**Architecture:** Two new `ParsedCommand` types (`is_discussion`, `is_debate`) handled by dedicated dispatch functions. Each mode runs multiple CLIRunners sequentially with structured prompts, then produces a synthesised conclusion.

**Tech Stack:** asyncio, existing CLIRunner, Tier3Store (for saving full transcripts)

---

## Background: Relay Mode (already implemented)

`/relay runner1,runner2 <prompt>` — chains runners sequentially; each receives the previous output as context.

---

## Task 1: Discussion Mode (`/discuss`)

**What it does:**
- User sends: `/discuss claude,gemini <question>`
- Round 1: Claude answers the question
- Round 2: Gemini critiques/extends Claude's answer (seeing original question + Claude's reply)
- Round 3: Claude responds to Gemini's critique
- Final: A designated "summariser" runner (default: last runner) synthesises into a conclusion

**Rounds:** Configurable, default = 3 (1 initial + 2 exchanges). Max = 6.

**Files:**
- Modify: `src/gateway/router.py` — add `is_discussion`, `discussion_runners`, `discussion_rounds`
- Modify: `main.py` — add `_dispatch_discussion()`
- Modify: `README.md`, `README.zh-TW.md`

### Steps

- [ ] **Step 1: Add ParsedCommand fields**

```python
# src/gateway/router.py — in ParsedCommand dataclass
is_discussion: bool = False
discussion_runners: list[str] = field(default_factory=list)
discussion_rounds: int = 3
```

- [ ] **Step 2: Parse `/discuss` command**

Syntax: `/discuss claude,gemini[,rounds=N] <prompt>`

```python
# in Router.parse(), before the /use block:
if text.startswith("/discuss "):
    rest = text[9:].strip()
    parts2 = rest.split(None, 1)
    if len(parts2) >= 1:
        runner_part = parts2[0]
        rounds = 3
        if ",rounds=" in runner_part:
            runner_part, rounds_str = runner_part.rsplit(",rounds=", 1)
            rounds = min(max(int(rounds_str), 2), 6)
        runners = [r.strip() for r in runner_part.split(",") if r.strip() in self._runners]
        prompt = parts2[1].strip() if len(parts2) > 1 else ""
        if len(runners) >= 2 and prompt:
            return ParsedCommand(
                runner=runners[0], prompt=prompt,
                is_discussion=True,
                discussion_runners=runners,
                discussion_rounds=rounds,
            )
```

- [ ] **Step 3: Implement `_dispatch_discussion()` in main.py**

```python
async def _dispatch_discussion(
    *, inbound, session, runners, tier3, send_reply,
    discussion_runners, discussion_rounds, prompt,
) -> None:
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="user", content=inbound.text)
    history: list[tuple[str, str]] = []  # (runner_name, response)

    for round_num in range(discussion_rounds):
        runner_name = discussion_runners[round_num % len(discussion_runners)]
        runner = runners.get(runner_name)
        if not runner:
            await send_reply(f"Runner '{runner_name}' not found.")
            continue

        label = f"[Round {round_num + 1} — {runner_name.upper()}]"
        await send_reply(f"{label} thinking...")

        # Build prompt with conversation history
        if not history:
            round_prompt = prompt
        else:
            history_text = "\n\n".join(
                f"{name.upper()}: {resp}" for name, resp in history
            )
            round_prompt = (
                f"Original question: {prompt}\n\n"
                f"Discussion so far:\n{history_text}\n\n"
                f"Your turn ({runner_name}): Please respond, critique, or build on the above."
            )

        chunks = []
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

    # Final synthesis
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
            synth_chunks = []
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
```

- [ ] **Step 4: Wire into dispatch() in main.py**

```python
if cmd.is_discussion:
    await _dispatch_discussion(
        inbound=inbound, session=session, runners=runners,
        tier3=tier3, send_reply=send_reply,
        discussion_runners=cmd.discussion_runners,
        discussion_rounds=cmd.discussion_rounds,
        prompt=cmd.prompt,
    )
    return
```

- [ ] **Step 5: Commit**

```bash
git add src/gateway/router.py main.py
git commit -m "feat: add discussion mode (/discuss runner1,runner2 prompt)"
```

---

## Task 2: 3-Way Debate Mode (`/debate`) with Majority Vote

**What it does:**
- User sends: `/debate claude,codex,gemini <question>`
- Round 1: All 3 runners independently answer the question (parallel)
- Round 2: Each runner sees all 3 answers and votes for the best approach (A/B/C) with reasoning
- Result: The answer with the most votes wins; ties go to a tiebreaker round
- Final: Winning runner elaborates on its answer with full context

**Why this is different from /discuss:**
- Answers are collected in parallel (faster)
- Explicit voting mechanism with majority decision
- Objective output: one winner, not an open-ended discussion

**Files:**
- Modify: `src/gateway/router.py` — add `is_debate`, `debate_runners`
- Modify: `main.py` — add `_dispatch_debate()`
- Modify: `README.md`, `README.zh-TW.md`

### Steps

- [ ] **Step 1: Add ParsedCommand fields**

```python
is_debate: bool = False
debate_runners: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Parse `/debate` command**

Syntax: `/debate claude,codex,gemini <prompt>` (exactly 3 runners)

```python
if text.startswith("/debate "):
    rest = text[8:].strip()
    parts2 = rest.split(None, 1)
    if len(parts2) >= 1:
        runners_list = [r.strip() for r in parts2[0].split(",")
                        if r.strip() in self._runners]
        prompt = parts2[1].strip() if len(parts2) > 1 else ""
        if len(runners_list) == 3 and prompt:
            return ParsedCommand(
                runner=runners_list[0], prompt=prompt,
                is_debate=True, debate_runners=runners_list,
            )
```

- [ ] **Step 3: Implement `_dispatch_debate()` in main.py**

```python
async def _dispatch_debate(
    *, inbound, session, runners, tier3, send_reply,
    debate_runners, prompt,
) -> None:
    import asyncio as _asyncio
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="user", content=inbound.text)
    await send_reply(f"[DEBATE] {' vs '.join(r.upper() for r in debate_runners)}")

    # Round 1: parallel answers
    async def _get_answer(runner_name: str) -> tuple[str, str]:
        runner = runners.get(runner_name)
        if not runner:
            return runner_name, "(runner not found)"
        chunks = []
        try:
            async for chunk in runner.run(
                prompt=prompt, user_id=inbound.user_id,
                channel=inbound.channel, cwd=session.cwd,
            ):
                chunks.append(chunk)
            return runner_name, "".join(chunks).strip()
        except Exception as e:
            logger.error("Debate answer error for %s: %s", runner_name, e, exc_info=True)
            return runner_name, f"(error: {e})"

    answers = dict(await _asyncio.gather(*[_get_answer(r) for r in debate_runners]))
    labels = {r: chr(65 + i) for i, r in enumerate(debate_runners)}  # A, B, C

    for runner_name, label in labels.items():
        await send_reply(f"[{label}] {runner_name.upper()}\n{answers[runner_name]}")

    # Round 2: each runner votes
    vote_prompt_template = (
        f"Original question: {prompt}\n\n"
        + "\n\n".join(f"Option {labels[r]} ({r}):\n{answers[r]}" for r in debate_runners)
        + "\n\nWhich answer is the most correct, complete, and actionable? "
          "Reply with ONLY the letter (A, B, or C) on the first line, "
          "then your reasoning on the next lines."
    )

    await send_reply("[VOTING] Each runner casting vote...")
    vote_results = dict(await _asyncio.gather(
        *[_get_answer_with_prompt(r, vote_prompt_template, inbound, session, runners)
          for r in debate_runners]
    ))

    # Tally votes
    tally: dict[str, int] = {r: 0 for r in debate_runners}
    for voter, vote_text in vote_results.items():
        first_line = vote_text.strip().split("\n")[0].strip().upper()
        for runner_name, label in labels.items():
            if first_line == label:
                tally[runner_name] += 1
                await send_reply(f"[{voter.upper()} votes {label}] {vote_text}")
                break

    winner = max(tally, key=tally.get)
    await send_reply(
        f"[RESULT] Winner: {winner.upper()} "
        f"({tally[winner]}/3 votes)\n\n"
        f"Winning answer:\n{answers[winner]}"
    )

    transcript = (
        f"Debate: {prompt}\n\n"
        + "\n\n".join(f"{r} [{labels[r]}]: {answers[r]}" for r in debate_runners)
        + f"\n\nWinner: {winner} ({tally[winner]} votes)"
    )
    await tier3.save_turn(user_id=inbound.user_id, channel=inbound.channel,
                          role="assistant", content=f"[debate] {transcript}")


async def _get_answer_with_prompt(runner_name, prompt, inbound, session, runners):
    runner = runners.get(runner_name)
    if not runner:
        return runner_name, "(not found)"
    chunks = []
    try:
        async for chunk in runner.run(
            prompt=prompt, user_id=inbound.user_id,
            channel=inbound.channel, cwd=session.cwd,
        ):
            chunks.append(chunk)
        return runner_name, "".join(chunks).strip()
    except Exception as e:
        return runner_name, f"(error: {e})"
```

- [ ] **Step 4: Wire into dispatch()**

```python
if cmd.is_debate:
    await _dispatch_debate(
        inbound=inbound, session=session, runners=runners,
        tier3=tier3, send_reply=send_reply,
        debate_runners=cmd.debate_runners, prompt=cmd.prompt,
    )
    return
```

- [ ] **Step 5: Update README bot commands table**

Add rows:
```
| `/discuss runner1,runner2[,rounds=N] <q>` | Multi-round discussion with synthesis |
| `/debate runner1,runner2,runner3 <q>`      | 3-way parallel debate with majority vote |
```

- [ ] **Step 6: Commit**

```bash
git add src/gateway/router.py main.py README.md README.zh-TW.md
git commit -m "feat: add 3-way debate mode with majority vote (/debate)"
```

---

## Command Summary (after all tasks)

| Command | Runners | Behaviour |
|---------|---------|-----------|
| `/relay a,b <q>` | 2+ | Sequential chain, each sees previous output |
| `/discuss a,b[,rounds=N] <q>` | 2+ | Turn-based discussion with final synthesis |
| `/debate a,b,c <q>` | exactly 3 | Parallel answers → voting → majority winner |
