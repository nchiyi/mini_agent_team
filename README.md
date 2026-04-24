# mini_agent_team (Project MAGI)

**The Pocket AI Software Company** — Bridge powerful local CLI agents (Claude Code, Gemini CLI, etc.) to Telegram and Discord. Featuring a "Virtual Agency" architecture, dual-tier persistent memory, and automated distillation.

> 繁體中文說明請見 [README.zh-TW.md](README.zh-TW.md)

---

## Architecture (Project MAGI)

```mermaid
flowchart TB
    %% External Platforms
    subgraph Clients ["Clients"]
        TG["📱 <b>Telegram</b>"]
        DC["🎮 <b>Discord</b>"]
    end
    
    subgraph Gateway ["MAGI Gateway"]
        direction TB
        Adapter["🔌 <b>Multi-platform Adapters</b>"]
        Router["🚦 <b>Semantic Router (NLU)</b>"]
        Session["⏳ <b>State Manager</b>"]
    end

    subgraph Agency ["Virtual Agency"]
        direction LR
        Role1["👨‍💻 <b>Code Auditor</b>"]
        Role2["🕵️ <b>Bug Hunter</b>"]
        Role3["🚀 <b>DevOps</b>"]
        Roster{{"📋 <b>Roster DNA</b>"}}
    end

    subgraph Memory ["Memory System"]
        direction LR
        T1[("📝 <b>Tier 1: Permanent</b><br/>Facts & Summaries")]
        T3[("📚 <b>Tier 3: Archive</b><br/>SQLite FTS5 Search")]
        Distill{"♻️ <b>Distillation</b>"}
    end

    subgraph Execution ["Execution Matrix"]
        direction TB
        Orchestrator{"🎭 <b>Orchestration</b><br/>Discuss / Debate / Relay"}
        Runner["🤖 <b>CLI Runners</b><br/>Claude / Gemini / Codex"]
    end

    %% Flows
    Clients --> Adapter
    Adapter --> Router
    Router --> Session
    Session --> Roster
    Roster --> Orchestrator
    Orchestrator <--> Memory
    Orchestrator --> Runner
    
    T3 -.->|Threshold Reached| Distill
    Distill -.->|Summarize| T1

    Runner -- "Streaming" --> Adapter

    %% Styling
    classDef platform fill:#f0f7ff,stroke:#0052cc,color:#0052cc,stroke-width:2px
    classDef magi fill:#fff9f0,stroke:#d4a017,color:#d4a017,stroke-width:2px
    classDef agency fill:#fdf2f2,stroke:#c53030,color:#c53030,stroke-width:2px
    classDef memory fill:#f3faf7,stroke:#2f855a,color:#2f855a,stroke-width:2px
    classDef exec fill:#f9f5ff,stroke:#6b46c1,color:#6b46c1,stroke-width:2px
    
    class Clients,TG,DC platform
    class Gateway,Adapter,Router,Session magi
    class Agency,Role1,Role2,Role3,Roster agency
    class Memory,T1,T3,Distill memory
    class Execution,Orchestrator,Runner exec
```

---

## Key Features

### 🏛️ Virtual Agency Architecture
More than just a chatbot — build an expert team with specific "Job DNA". Define mission and rules in `roster/*.md`, and the system will automatically route your natural language requests (e.g., "Audit this code for security") to the most suitable role (e.g., `code-auditor`).

### 🧠 Memory Distillation
Solve the "context explosion" problem. When conversation history grows too long, the system automatically summarizes older turns into permanent facts (Tier 1), ensuring the AI remembers key decisions without bloating the prompt.

### 🎭 Multi-Agent Orchestration
Built-in **Discuss**, **Debate**, and **Relay** modes. Let Claude and Gemini debate an architectural decision to provide you with balanced, high-fidelity development advice.

### ⚡ Extreme Streaming
Powered by our custom Streaming Bridge, you can see real-time progress from CLI tools and long code generations instantly on your mobile device, reducing latency and improving interactivity.

---

## Quick Start

### Prerequisites
- Python 3.12+
- At least one CLI Agent installed: `claude` (Claude Code) or `gemini` (Gemini CLI).
- Telegram and/or Discord Bot Token.

### One-liner Installation (Recommended)
```bash
curl -fsSL https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh | bash
```

---

## Command Encyclopedia

| Category | Command | Description |
|----------|---------|-------------|
| **Expert System** | `/claude`, `/gemini` | Call a specific AI runner directly |
| | `/use <slug>` | Manually switch to a specific Roster role |
| **Collaboration** | `/discuss <r1,r2> [p]` | Multi-agent brainstorming session |
| | `/debate <r1,r2> [p]` | Comparative debate between agents |
| | `/relay <r1,r2> [p]` | Sequential agent pipeline |
| **Memory** | `/remember <text>` | Save a permanent fact (Tier 1) |
| | `/recall <query>` | Full-text search of history (Tier 3) |
| **System** | `/status`, `/usage` | Check system health and token stats |
| | `/new` or `/reset` | Reset current session and context |
| | `/cancel` | Immediately stop AI generation |
| | `/voice on/off` | Toggle speech-to-text functionality |

---

## Project Structure

```text
mini_agent_team/
├── main.py                # Core entry point (The Brain)
├── roster/                # Expert Role DNA definitions
├── src/
│   ├── gateway/           # NLU & Semantic routing core
│   ├── core/memory/       # Dual-tier storage & distillation
│   ├── agent_team/        # Orchestration logic
│   └── runners/           # Async CLI monitoring
├── modules/               # Plugins (Web Search, Vision)
└── config/                # System config & deployment scripts
```

---

## Security & Policy

- **Privacy First**: Memory is strictly isolated by `(user_id, channel)`.
- **Fail-Closed**: `ALLOWED_USER_IDS` is mandatory; empty list locks the bot.
- **Policy**: This platform is for personal remote control only. Multi-user proxying of licensed CLI tools like Claude Code is strictly prohibited.

---

## License

MIT License
