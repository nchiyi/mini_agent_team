# OpenAB Architecture Research

研究 [openabdev/openab](https://github.com/openabdev/openab) 的設計，標註哪些值得借鏡到 MAT、哪些不適合。

研究時間：2026-04-28
研究背景：MAT Docker 模式下 bot 收到訊息但 dispatch 失敗 — `claude-agent-acp` 在容器內報 `{'code': -32000, 'message': 'Authentication required'}`。原因是 macOS Claude Code 把 OAuth 存在 Keychain，沒辦法從容器讀取。OpenAB 是 K8s 專案，他們對「headless container OAuth」有現成解。

---

## 借鏡的部分（Phase 1 採用）

### 1. 容器內裝置碼登入

OpenAB 對每個 CLI agent 提供一個一次性互動指令完成 OAuth：

| CLI | 登入指令 | 來源 |
|-----|---------|------|
| claude | `claude setup-token` | docs/claude-code.md:39 |
| codex | `codex login --device-auth` | docs/codex.md auth section |
| gemini | Google OAuth flow（互動）或 `GEMINI_API_KEY` | docs/gemini.md:38-44 |
| opencode | `opencode auth login` | docs/opencode.md:62 |
| kiro | `kiro-cli login --use-device-flow` | docs/kiro.md auth section |
| cursor | `cursor-agent login`（在 `bash` 互動殼內）| docs/cursor.md auth section |
| copilot | `copilot login` + `gh auth login -p https -w` | docs/copilot.md:78 |

K8s 端：`kubectl exec -it deploy/X -- <cli> <login-cmd>`
Compose 端：`docker compose exec -it gateway <cli> <login-cmd>`

### 2. 持久化 volume 掛在 `$HOME`

每個 agent 一個 PVC，掛在 container 的 `$HOME`（`/home/node` for Claude/Codex/Gemini/OpenCode；`/home/agent` for Cursor/Kiro）。

OpenAB chart：`charts/openab/values.yaml` 預設 `persistence.enabled = true, size = 1Gi`。
deployment.yaml:N 引用：`mountPath: {{ $cfg.workingDir | default "/home/agent" }}`

OAuth token 寫進 PVC，container 重啟 / image 重 build 都不掉。

### 3. `CLAUDE_CODE_EXECUTABLE` env var（重要 gotcha）

`Dockerfile.claude:14`：
```
ENV CLAUDE_CODE_EXECUTABLE=/usr/local/bin/claude
```

註解直接點明：
> Without CLAUDE_CODE_EXECUTABLE the adapter uses its own bundled SDK cli.js,
> ignoring the globally installed claude-code binary (see #418).

如果不設這個環境變數，`@agentclientprotocol/claude-agent-acp` 會跑自己 npm 套件裡 bundled 的 cli.js（一個獨立的 SDK），完全忽略我們 npm install 的全域 claude binary。我們之前可能就踩到這個。

### 4. npm 套件版本 pin

OpenAB Dockerfile 用 ARG：
```
ARG CLAUDE_AGENT_ACP_VERSION=0.29.2
ARG CLAUDE_CODE_VERSION=2.1.116
RUN npm install -g @agentclientprotocol/claude-agent-acp@${CLAUDE_AGENT_ACP_VERSION} ...
```

MAT 可在 `requirements.npm.txt` 加版號做到同樣效果。

---

## 不採用的部分（保留分析供日後評估）

### 不採用 1. 每個 CLI 一個獨立 image + 獨立 bot

| 優點 | 缺點 |
|------|------|
| Image size：每個 image 只裝一個 CLI 的 dep，~200-400MB / 個 | 每多一個 agent 要再申請一個 Telegram bot token |
| 獨立版本鎖：claude 升級不影響 codex | N container 同時跑 = N × ~200MB 常駐 RAM |
| 失敗隔離：claude 崩了 codex 還能用 | 失去 MAT 的 `/discuss` `/debate` `/relay` 多 agent 協作 |
| 每個 agent 自己一份 OAuth、可獨立撤銷 | 失去語義路由（user 一句話自動選 claude/codex/gemini）|
| Token 不再共用 → 不會像 2026-04-28 撞 Linux openclaw | 每多一個 agent 多一條設定流程 |
| Mental model 清楚：`@nchiyi_claude_bot` 就是 claude | 同房間多個 bot 使用者要記哪個是哪個 |

**判決**：MAT 是「個人助理 + 統一閘道」場景，OpenAB 是「team / org / multi-tenant」場景。MAT 不需拆。要做等於整個重寫 gateway。

### 不採用 2. Helm / K8s PVC / ConfigMap

| 優點 | 缺點 |
|------|------|
| 生產級 orchestration：rolling restart、liveness probe、resource limits | **要先有 K8s cluster** — 個人 Mac 不該為跑 bot 裝 k3s |
| Declarative：`helm install --set ...` 100% reproducible | 控制平面 idle 吃 1-2GB RAM |
| Multi-tenant：namespace、RBAC、Secret 整合 vault | 學習曲線：helm + kubectl + manifest vs `mat start` |
| 進階監控：Prometheus / Grafana / Loki / OpenTelemetry | 迭代週期慢：`helm upgrade` 比 `docker compose up -d` 重 |
| Scale-out：replicas、PDB、HPA 全部現成 | log 多一層抽象：`kubectl logs` vs `mat logs` |
| ConfigMap 把 config 跟 code 解耦得很乾淨 | docker-compose named volume 已能做大部分 PVC 該做的事 |

**判決**：MAT 用 docker-compose 完全夠用。除非要部署到雲端 cluster 服務多個用戶才考慮。

### 不採用 3. Threading-based 訊息路由（@mention 後開 thread）

| 優點 | 缺點 |
|------|------|
| 對話歷史乾淨：每個主題一條 thread | **Telegram 一般私訊根本沒 thread**（Forum 模式有但體驗差）|
| 同一 channel 可放多個 bot 互不干擾 | Discord / Slack 才有原生 thread；Telegram 私訊 1:1 沒這需求 |
| 自動分組：scrollable archive、search-friendly | 改變使用者習慣：要記得「先 @mention 開 thread」 |
| 噪音少：channel 裡只看到啟動訊息，細節在 thread | 跟私訊（最常見的個人用法）不相容 |
| 每個 thread 自己的 ACP session 隔離 | bot 要追蹤 `thread_id`（MAT 目前用 `user_id` 分桶，本質類似） |

**判決**：Telegram 私訊場景 thread 模型不適用。Discord / Slack 場景可以借鏡，但 MAT 主要走 Telegram，先不做。

### 不採用 4. Per-thread session pool + suspend / resume

| 優點 | 缺點 |
|------|------|
| 處理超過 `max_sessions` 數量的 thread（oldest idle suspend）| 複雜：suspended map、cancel handles、create gate、lock ordering |
| 記憶體效率：idle session 不佔 active slot | ACP `session/load` 各 CLI 實作不一致 |
| 復活對話延續性：一週後回來繼續同一個 session | MAT 已有雙層記憶（T1/T3），long-running 連續性已解 |
| 有上限避免資源無限增長 | 個人用戶 1-2 個並行對話，pool 10 太多 |
| | OpenAB pool.rs:9 註明「lock ordering: never await per-connection mutex while holding state」— 公認難搞 |

**判決**：MAT idle 60 分鐘直接終止 + T1/T3 記憶救回，已是更輕量解。pool 對個人沒意義。

### 不採用 5. Non-root user + readOnlyRootFilesystem

| 優點 | 缺點 |
|------|------|
| **安全**：least privilege；RCE 也只能寫指定的可寫 mount | 額外 setup：chown OAuth 目錄到 non-root、tini 當 init |
| 業界 best practice（CIS Docker Benchmark、NSA hardening）| npm post-install script 寫 /usr/local 的會壞掉 |
| Defense-in-depth：claude CLI 漏洞 blast radius 縮小 | Debug 難：不能臨時 `apt install` 補工具 |
| Cloud Run / ECS Fargate / k8s securityContext 環境必要 | 一些 CLI 假設 `HOME=/root` 或固定 UID，可能要 patch |
| 強迫架構乾淨：state 跟 code 分離 | 個人 Mac 容器不對外，攻擊面小，邊際效益低 |

**判決**：值得做但不影響當前 auth 問題。Phase 3 安全強化獨立做。

---

## 推薦採用順序

| 階段 | 內容 | 工作量 |
|------|------|-------|
| **Phase 1** | 容器內 OAuth 登入流程 + 持久化 volume + `CLAUDE_CODE_EXECUTABLE` env + npm 版本 pin | ~40 min |
| Phase 2 | （保留）npm 套件版本 pin、HEALTHCHECK 強化 | ~15 min |
| Phase 3 | （保留）Non-root user + readOnlyRootFilesystem | ~30-60 min（要驗證每個 CLI 在非 root 下能跑）|
| Phase 4 | （視需要）Discord thread-based routing | TBD |
| 不規劃 | 多 image 多 bot、Helm/K8s、進階 session pool | — |

## Path B 多 bot 進度（與上表獨立）

| 階段 | 內容 | 工作量 | 狀態 |
|------|------|-------|------|
| **B-1** | 一個 MAT process 服務 N 個 Telegram bot；私訊 only；per-bot 預設 runner + role；memory 以 `(user_id, channel, bot_id)` 隔離 | ~6-8 小時 | **Done** — 見 multi-bot-feature 分支 |
| B-2 | 同樣的 bot 們進到同一個群組；@mention / 自然語言定址；bot 之間可辯論；輪數上限防止迴圈；per-group memory 隔離 | +~6-8 小時 | 規劃中（plan: `/home/kiwi/.claude/plans/async-crunching-popcorn.md`） |

B-1 涵蓋 plan task 1-9（task 9 縮小範圍：互動 wizard loop 延後，capability 已透過手動編 config.toml 完整可用）。Task 10 為本文件 + README 多 bot 設定章節。

---

## 參考路徑（OpenAB repo）

repo: <https://github.com/openabdev/openab>

| 主題 | 路徑 |
|------|------|
| 各 CLI 的 Dockerfile | `Dockerfile.claude` / `.codex` / `.gemini` / `.opencode` / `.cursor` / `.copilot` |
| 各 CLI 的 auth doc | `docs/{claude-code,codex,gemini,kiro,cursor,copilot,opencode}.md` 的 `## Authentication` 章節 |
| Helm chart 結構 | `charts/openab/templates/{deployment,configmap,secret,pvc}.yaml` |
| Helm values 預設 | `charts/openab/values.yaml`（特別是 `agents.<name>.persistence`、`pool`）|
| Rust ACP pool（含 suspend/resume 邏輯）| `src/acp/pool.rs`（627 lines）|
| Rust ACP 連線層 | `src/acp/connection.rs` |
| Rust ACP JSON-RPC 協議 | `src/acp/protocol.rs`（338 lines）|
| 設定精靈 | `src/setup/{wizard,validate,config}.rs` |
| 訊息模型 / threading 設計 | `docs/messaging.md` |
| 多 agent 部署 | `docs/multi-agent.md` |
