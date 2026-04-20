# mini_agent_team

A versatile multi-channel AI gateway that bridges Telegram and Discord to local CLI-based AI agents such as Claude Code, Codex, and Gemini. Interact with your preferred AI agents directly from your mobile device with persistent memory, full-text search capabilities, and a modular plugin architecture.

---

## Architecture

```
Telegram / Discord
       │
       ▼
  Channel Adapters  (src/channels/)
       │
       ▼
    Gateway         (src/gateway/router.py)
       │
       ├── Built-in commands  (/remember, /forget, /recall, /status, /switch)
       │
       └── CLI Runners        (src/runners/cli_runner.py)
                │
                ├── Claude Code  (claude --dangerously-skip-permissions)
                ├── OpenAI Codex (codex exec)
                ├── Gemini CLI   (gemini)
                └── custom runners (configurable)

Memory System:
  Tier 1: Persistent per-user/per-channel facts (JSONL, high-speed access)
  Tier 3: Comprehensive conversation history (SQLite WAL + FTS5 search)
```

---

## Key Features

- **Multi-Platform Support**: Seamlessly integrate Telegram and Discord within a single process.
- **Dynamic Agent Switching**: Hot-swap between different AI runners at runtime using commands like `/claude`, `/codex`, or `/gemini`.
- **Real-time Streaming**: Enjoy live message updates as the runner generates output chunks.
- **Advanced Persistent Memory**: Dual-tier storage featuring permanent user notes and searchable conversation history.
- **Modular Plugin System**: Easily extend functionality with drop-in modules for web search, computer vision, and specialized dev agents.
- **Interactive Setup**: Streamlined configuration via a built-in interactive wizard (`python -m src.setup.wizard`).
- **Comprehensive Audit Logs**: Maintain accountability with append-only daily JSONL logs of all runner interactions.

---

## Quick Start

### Prerequisites

- Python 3.11+
- At least one CLI agent installed: `claude`, `codex`, or `gemini`
- A Telegram Bot Token (via [@BotFather](https://t.me/botfather)) and/or a Discord Bot Token.

### Installation

```bash
git clone https://github.com/nchiyi/mini_agent_team.git
cd mini_agent_team
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Launch the interactive setup wizard:

```bash
python -m src.setup.wizard
```

Alternatively, configure the environment manually:

```bash
cp config/config.toml.example config/config.toml
cp .env.example secrets/.env
# Update secrets/.env with your tokens and ALLOWED_USER_IDS
```

### Execution

```bash
python main.py
```

---

## Detailed Configuration

### `secrets/.env`

```env
TELEGRAM_BOT_TOKEN=your_telegram_token
DISCORD_BOT_TOKEN=your_discord_token      # optional
ALLOWED_USER_IDS=123456789,987654321      # required — leave empty to lock the bot
```

> **Security Note:** The `ALLOWED_USER_IDS` field is mandatory. An empty list will lock the bot, preventing any unauthorized access.

### `config/config.toml`

Key configuration parameters:

```toml
[gateway]
default_runner = "claude"
session_idle_minutes = 60
stream_edit_interval_seconds = 1.5

[runners.claude]
path = "claude"
args = ["--dangerously-skip-permissions"]
timeout_seconds = 300
context_token_budget = 4000

[memory]
db_path = "data/db/history.db"
cold_permanent_path = "data/memory/cold/permanent"
tier3_context_turns = 20
```

---

## Bot Commands

| Command | Description |
|---------|-------------|
| `/remember <text>` | Save a permanent note to your memory |
| `/forget <keyword>` | Remove permanent notes matching the keyword |
| `/recall <query>` | Perform a full-text search of your conversation history |
| `/status` | View current runner, token usage, and session information |
| `/claude` | Switch to the Claude Code runner |
| `/codex` | Switch to the Codex runner |
| `/gemini` | Switch to the Gemini CLI runner |
| `/new` | Terminate the current session and start fresh |

*All other messages are automatically forwarded to the active runner and streamed back to the user.*

---

## Memory System Architecture

| Tier | Storage Engine | Purpose |
|------|----------------|---------|
| Tier 1 | Per-user JSONL | High-priority facts and user-defined notes via `/remember` |
| Tier 3 | SQLite (FTS5) | Searchable, long-term conversation history |

**Context Injection:** Prompts are automatically enriched by prepending Tier 1 notes followed by the most recent Tier 3 dialogue turns (configured via `tier3_context_turns`).

---

## Module System

Extend the gateway by placing module directories under `modules/`. Each module must contain a `handler.py` that exports an `AsyncGenerator` handler. Modules are automatically discovered during the startup sequence.

### Included Modules:
- `dev_agent`: Delegates complex tasks to a sub-agent with git worktree access.
- `web_search`: Integrates DuckDuckGo or Tavily for real-time web results.
- `vision`: Provides image description capabilities via multimodal APIs.

---

## Deployment

### Systemd (User Service)

The setup wizard can automatically generate a systemd unit file for you:

```bash
python -m src.setup.wizard
systemctl --user enable --now gateway-agent
```

### Docker

```bash
docker compose up -d
```

---

## Project Structure

```
main.py                    Entry point
src/
  channels/
    telegram.py            Telegram adapter
    discord_adapter.py     Discord adapter
    base.py                BaseAdapter interface
  gateway/
    router.py              Command parsing and routing logic
    session.py             Per-user session state management
    streaming.py           Streaming bridge for real-time updates
  core/
    memory/
      tier1.py             Permanent memory management
      tier3.py             SQLite history and search engine
      context.py           Token-aware context assembly
    config.py              Configuration loader
  runners/
    cli_runner.py          Subprocess-based runner wrapper
    audit.py               Asynchronous audit logging
  modules/
    loader.py              Module auto-discovery system
  setup/
    wizard.py              Interactive configuration wizard
    deploy.py              Deployment script generator
    installer.py           CLI tool installation utility
modules/                   Directory for drop-in plugins
config/                    Generated config.toml
secrets/                   Generated .env (protected with chmod 600)
data/                      Runtime data (databases, memory, logs)
```

---

## License

This project is licensed under the MIT License.
