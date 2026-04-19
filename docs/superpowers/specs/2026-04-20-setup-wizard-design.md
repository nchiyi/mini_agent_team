# Setup Wizard (Phase 5) — Design Spec

**Date:** 2026-04-20
**Repo:** nchiyi/telegram-to-control
**Phase:** 5 of Gateway Agent Platform

---

## Goal

Provide a single interactive Python wizard (`setup.py`) that lets a new user configure and launch the Gateway Agent Platform in under 5 minutes. The wizard writes `config/config.toml` and `secrets/.env`, optionally installs missing CLI tools and Ollama in the background, and launches the bot when done.

---

## Architecture

```
setup.py                    ← entry point: asyncio.run(main())

src/setup/
  __init__.py
  wizard.py                 ← step orchestrator, state machine
  state.py                  ← load/save data/setup-state.json
  validator.py              ← token validation (Telegram + Discord HTTP)
  installer.py              ← background CLI/Ollama installation
  deploy.py                 ← write config.toml, .env, systemd unit, docker-compose
```

---

## Step Flow

| Step | Name | Description |
|------|------|-------------|
| 1 | Channel selection | Choose Telegram / Discord / both |
| 2 | Token entry | Enter bot token(s); validate via HTTP; allow re-entry on failure |
| 3 | Allowlist | Start temporary bot listener; user sends test message; capture user_id automatically. 30s timeout → fall back to manual input |
| 4 | CLI selection | Multi-select claude/codex/gemini/kiro; detect already-installed; install missing ones in background |
| 5 | Search mode | FTS5 (default) or FTS5+embedding; embedding triggers background Ollama install |
| 6 | Update notifications | On/off toggle; if on, check GitHub releases on startup and print notice (never auto-update) |
| 7 | Deploy mode | foreground / systemd / docker; write appropriate config files |
| 8 | Launch | Write config.toml + secrets/.env; create data dirs; start bot per chosen deploy mode |

---

## Resume Mechanism

Completed step numbers are stored in `data/setup-state.json`:

```json
{
  "completed_steps": [1, 2, 3],
  "channel": "telegram",
  "telegram_token": "...",
  "allowed_user_ids": [123456],
  "selected_clis": ["claude", "codex"],
  "search_mode": "fts5",
  "update_notifications": true,
  "deploy_mode": "systemd"
}
```

On re-run, the wizard loads this file and skips steps already in `completed_steps`. The user can force a full re-run with `python setup.py --reset`.

**Data safety:** The wizard never touches `data/memory/` or `data/db/`.

---

## Token Validation

**Telegram:** `GET https://api.telegram.org/bot{token}/getMe` via `urllib.request`.
- 200 + `"ok": true` → valid
- 401/other → invalid; prompt to re-enter

**Discord:** `GET https://discord.com/api/v10/users/@me` with `Authorization: Bot {token}`.
- 200 → valid
- 401 → invalid; prompt to re-enter

Validation uses `urllib.request` (stdlib, no extra deps).

---

## Allowlist Acquisition (Step 3)

1. Start a minimal `python-telegram-bot` `Application` (already in requirements.txt)
2. Print: `"Send any message to your bot now (waiting 30s)..."`
3. On first message received: capture `update.effective_user.id`, stop the listener
4. If 30s elapses with no message: fall back to `input("Enter your Telegram user ID: ")`
5. For Discord: manual input only (Discord bot listeners require gateway intents setup)

---

## CLI Installation (Step 4)

Detection: `shutil.which(name)` — if binary found, mark as already installed.

Install commands:
| CLI | Install command |
|-----|----------------|
| claude | `npm install -g @anthropic-ai/claude-code` |
| codex | `npm install -g @openai/codex` |
| gemini | `npm install -g @google/generative-ai` (or `pip install google-generativeai`) |
| kiro | `npm install -g @aws/kiro` |

Install runs as a background `asyncio.create_subprocess_exec` task. The wizard continues to the next step immediately. Progress shown every 30s in the terminal as `[background] Installing claude... (30s elapsed)`.

If install fails: print a warning with the manual install command; do not block setup.

---

## Ollama Installation (Step 5, embedding mode only)

Background install via the official script:
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

After install, pull the embedding model:
```bash
ollama pull nomic-embed-text
```

Both run as background subprocess. Progress shown every 30s. Bot launch waits for Ollama only if embedding mode was selected.

---

## Deployment Modes (Step 7)

### foreground
No extra files. Launch command: `venv/bin/python3 main.py`

### systemd
Write `~/.config/systemd/user/gateway-agent.service`:
```ini
[Unit]
Description=Gateway Agent Platform
After=network.target

[Service]
WorkingDirectory={cwd}
ExecStart={cwd}/venv/bin/python3 main.py
Restart=always
RestartSec=5
Environment="PATH={cwd}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=default.target
```
Then: `systemctl --user daemon-reload && systemctl --user enable --now gateway-agent`

### docker
Write `docker-compose.yml`:
```yaml
services:
  gateway:
    build: .
    restart: unless-stopped
    volumes:
      - ./config:/app/config:ro
      - ./secrets:/app/secrets:ro
      - ./data:/app/data
    environment:
      - PYTHONUNBUFFERED=1
```
Write minimal `Dockerfile` if not present. Launch: `docker compose up -d`

---

## Config Files Written

### config/config.toml
Populated from wizard answers. Non-secret values only. Missing runners are omitted.

### secrets/.env
```
TELEGRAM_BOT_TOKEN=...
DISCORD_BOT_TOKEN=...
ALLOWED_USER_IDS=123456
DEFAULT_CWD=/home/user
```

### Data directories created
```
data/memory/hot/
data/memory/cold/permanent/
data/memory/cold/session/
data/db/
data/audit/
```
(Only created if not already present — no data is cleared.)

---

## Implementation Notes

- **No new runtime dependencies** — uses only stdlib + packages already in requirements.txt
- **Pure `input()` prompts** — ANSI colour via `\033[...]` escape codes (no rich/questionary)
- **`asyncio.run(main())`** — the entire wizard runs in an async context for background tasks
- **Background tasks** are `asyncio.Task` objects; tracked in a list; progress printed by a periodic coroutine
- **`--reset` flag** — deletes `data/setup-state.json` and re-runs all steps

---

## Acceptance Criteria (from spec §9.3)

- [ ] Complete setup flow in <5 minutes (excluding downloads)
- [ ] Token error → clear error message, can re-enter without restarting
- [ ] CLI install runs in background; setup flow continues immediately
- [ ] After setup, bot starts automatically without extra commands
- [ ] Re-running setup does not clear `data/memory/` or `data/db/`
- [ ] Mid-setup failure → re-run resumes from last completed step

---

## Tests

**test_state.py** — load/save/reset state file, completed_steps tracking

**test_validator.py** — mock urllib.request; valid token returns True; 401 returns False

**test_installer.py** — mock asyncio subprocess; detect already-installed binary; background install task completes

**test_deploy.py** — write config.toml, .env, systemd unit, docker-compose to tmpdir; verify content

**test_wizard.py** — mock all steps; verify step sequencing, resume skips completed steps, --reset clears state

---

## Out of Scope

- Automatic version updates (only print notice)
- Multi-user setup (single operator)
- Web-based setup UI
- Windows support (Linux/macOS only)
