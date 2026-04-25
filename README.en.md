# mini_agent_team (Project MAGI)

**The Pocket AI Software Company** — Bridge powerful local CLI agents (Claude Code, Gemini CLI, Codex) to Telegram and Discord via persistent ACP sessions. Zero cold-start, full tool use, OAuth-only auth.

> 繁體中文主文件請見 [README.md](README.md)

---

## Key Features

- **Zero cold-start latency**: ACP (Agent Client Protocol) keeps agent processes alive between messages. Response time drops from 2–4s to milliseconds.
- **Full tool use**: MAT auto-approves all tool requests (bash, SSH, web search, MCP) via the ACP client — no `--dangerously-skip-permissions` flag needed in config.
- **OAuth-only auth**: Claude, Codex, and Gemini use your personal subscription OAuth. No API keys required or accepted.
- **Multi-platform**: Telegram and Discord in a single process.
- **Virtual Agency**: Define expert roles in `roster/*.md`; the semantic router picks the right specialist automatically.
- **Multi-agent orchestration**: Discuss, Debate, and Relay modes for collaborative AI workflows.
- **Memory distillation**: Auto-summarizes long conversations into Tier 1 facts.
- **Dual-tier storage**: Tier 1 permanent facts (JSONL) + Tier 3 full-text-searchable history (SQLite FTS5).

---

## Quick Start

### Prerequisites

- Git, Python 3.11+, Node.js 18+
- At least one CLI agent: `claude` (Claude Code), `gemini` (Gemini CLI), or `codex`
- A Telegram and/or Discord Bot Token

### One-liner install

```bash
curl -fsSL https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh | bash
```

### Manual install

```bash
git clone https://github.com/nchiyi/mini_agent_team.git
cd mini_agent_team
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
npm install -g @agentclientprotocol/claude-agent-acp @zed-industries/codex-acp
python3 -m src.setup.wizard
```

---

## Configuration

### `secrets/.env`
```env
TELEGRAM_BOT_TOKEN=your_token
DISCORD_BOT_TOKEN=your_token       # optional
ALLOWED_USER_IDS=123456789         # required — empty = deny all
```

### `config/config.toml`
```toml
[gateway]
default_runner = "claude"
session_idle_minutes = 60
stream_edit_interval_seconds = 0.5

[runners.claude]
type = "acp"
path = "claude-agent-acp"
args = []

[runners.codex]
type = "acp"
path = "codex-acp"
args = []

[runners.gemini]
type = "acp"
path = "gemini"
args = ["--acp", "--yolo"]
```

---

## Bot Commands

| Command | Description |
|---------|-------------|
| `/claude`, `/gemini`, `/codex` | Switch active runner |
| `/use <role>` | Switch to a Roster specialist |
| `/discuss <r1,r2>` | Multi-agent brainstorm |
| `/debate <r1,r2>` | Multi-agent debate |
| `/remember <text>` | Save permanent fact (Tier 1) |
| `/recall <query>` | Search conversation history (Tier 3) |
| `/status`, `/usage` | System health and token stats |
| `/new`, `/cancel` | Reset session or stop generation |

---

## Discord Message Source Control

The Discord adapter exposes three independent flags that control which messages the bot processes. They live in `[discord]` inside `config/config.toml`.

| Flag | Values | Default | Governs |
|------|--------|---------|---------|
| `allow_user_messages` | `off` / `mentions` / `all` | `all` | Human (non-bot) messages |
| `allow_bot_messages` | `off` / `mentions` / `all` | `off` | Other Discord bot messages |
| `trusted_bot_ids` | list of bot user IDs | `[]` (any) | ID allowlist when `allow_bot_messages != "off"` |

**Key points**
- The two flags are evaluated independently — a change to one has no effect on the other.
- `trusted_bot_ids` is only meaningful when `allow_bot_messages` is `"mentions"` or `"all"`. An empty list means all bots pass the ID check; a non-empty list restricts to listed IDs only.
- Human-user authorization (`ALLOWED_USER_IDS`) is still enforced on top of `allow_user_messages`.

### Typical Scenarios

#### (a) Personal assistant — humans only
Accept messages from authorized humans; ignore all other bots.
```toml
[discord]
allow_user_messages = "all"
allow_bot_messages  = "off"
```

#### (b) Multi-bot relay — trusted bots only
Accept messages from specific relay bots (and still serve humans).
```toml
[discord]
allow_user_messages = "all"
allow_bot_messages  = "all"
trusted_bot_ids     = [123456789012345678, 987654321098765432]
```

#### (c) Public server — respond only when @mentioned
In a busy server, only react when explicitly @mentioned by either humans or trusted bots.
```toml
[discord]
allow_user_messages = "mentions"
allow_bot_messages  = "mentions"
trusted_bot_ids     = [123456789012345678]
```

---

## License

MIT License
