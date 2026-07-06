# Changelog

All notable changes to AI Career Copilot are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions align with
the internal PMO roadmap (`~/doc/agent/doc/PMO_review_and_restructure.md`).

## [1.0.0] — 2026-07-06 · GA (Retention Loop)

### Added

- **Analysis Agent + API** (`backend/app/agents/analysis.py`,
  `backend/app/services/analysis_service.py`, `backend/app/api/v1/analysis.py`)
  - `POST /api/v1/analysis/assess` — 触发能力评估并落库 `ability_assessments`
  - `GET /api/v1/analysis/radar` — 返回最近能力雷达数据（含 evidence）
  - `GET /api/v1/analysis/trend` — 维度趋势查询
  - `POST /api/v1/analysis/gap` — 目标差距结构化输出（MVP）
- **Job Agent + API** (`backend/app/agents/job.py`,
  `backend/app/services/job_service.py`, `backend/app/api/v1/jobs.py`)
  - `POST /api/v1/jobs/kit` / `GET /api/v1/jobs/kit/{id}` — 面试题库 + pitch
  - `POST /api/v1/jobs/debrief` — 面试复盘落库并回填 Profile `achievement`
- **Redis Streams 事件层（v1.0）**
  - `backend/app/services/event_bus.py`：统一 `EventPublisher`（`maxlen=100000`）
  - `backend/app/events/consumer.py`：`xreadgroup` 消费骨架（ACK + pending 重试）
  - GitHub webhook 增加 `SYNC_EVENT_MODE=direct|dual|event` 路由策略，
    支持 `events:sync.github` 双写/纯事件模式切换
  - 新增事件发布：`events:task.completed`（Analysis/Job 完成后）
- **Document Ingest（PDF/DOCX）**
  - `POST /api/v1/documents/upload`（202 Accepted）
  - 文档原文写入 `document_blobs`，摘要提取后回填 Profile
- **Trust Ladder API**
  - `GET /api/v1/trust/level` / `POST /api/v1/trust/level`（L1-L3）
  - `TRUST_LADDER_L2_ENABLED` 开关控制 L2 放量
- **Growth Report API**
  - `POST /api/v1/reports/monthly` — 生成月度成长报告（`growth_reports`）
  - `GET /api/v1/reports/monthly` — 按 period 拉取历史报告
- **Calendar/Jira OAuth & Webhook 接口框架**
  - `GET /api/v1/oauth/calendar|jira/authorize`
  - `GET /api/v1/oauth/calendar|jira/callback`
  - `POST /api/v1/webhooks/calendar|jira`（最小字段发布到 `events:sync.*`）

### Changed

- `MasterAgent` 扩展意图：`ability_assessment` / `interview_kit`，并能路由到
  `AnalysisAgent` / `JobAgent`
- `app.main` 生命周期和路由升级到 v1.0 组件装配（4 Agent + 新 API 组）
- 版本号升级：
  - `backend/app/__init__.py` → `1.0.0`
  - `backend/pyproject.toml` → `1.0.0`

### Migration

- **`0004_v10_ga_core.py`**（Alembic）新增表：
  - `ability_assessments`
  - `growth_reports`
  - `interview_kits`
  - `interview_debriefs`
  - `trust_ladder_state`
  - `document_blobs`

## [0.8.0] — 2026-07-06 · Beta+ (Data Flywheel)

### Added

- **GitHub OAuth 2.0 integration** (`app/integrations/github.py`,
  `app/services/oauth_service.py`)
  - `GET /api/v1/oauth/github/authorize` — issues state cookie + returns
    `authorize_url` for the client to redirect to
  - `GET /api/v1/oauth/github/callback` — exchanges the code, upserts an
    encrypted `oauth_connections` row, links `users.github_user_id`
  - `GET /api/v1/oauth/github/callback/redirect` — same, but bounces the user
    back to the SPA with `?oauth=ok|error`
  - `GET /api/v1/oauth` / `DELETE /api/v1/oauth/{provider}` — list / unlink
  - Scopes default to `read:user user:email repo` (minimal read-only set)
- **GitHub Webhook receiver** (`app/api/v1/webhooks.py`)
  - `POST /api/v1/webhooks/github` — verifies `X-Hub-Signature-256` (HMAC-SHA256,
    constant-time compare), routes `pull_request` / `push` events through the
    Data Minimizer, delegates to `GitHubSyncService.ingest_webhook`
  - `ping` events → `pong` (for the "Test delivery" button on GitHub)
- **GitHub sync service** (`app/services/github_sync_service.py`)
  - `POST /api/v1/oauth/github/sync` — manual pull of the user's recent PRs
  - Idempotent via `sync_events (provider, external_id)` UNIQUE + record ledger
  - Returns `{fetched, created, updated, skipped_duplicates}` so the UI can
    show non-trivial progress
- **Profile Engine 3rd-party ingest** (`ProfileEngine.ingest_third_party`)
  - Adds `profile_entries.source_ref` column (e.g. `github:pr:{node_id}`,
    `github:repo:{full_name}`, `github:commit:{repo}:{i}:{prefix}`)
  - Same-`source_ref` re-arrivals update content but MUST NOT bump
    `occurrences` — protects the confidence score from webhook-replay inflation
  - Provenance ordering upgraded: `user_input > github > resume_import > generation`
  - `github_pr_to_candidates` / `github_push_to_candidates` in
    `app/services/profile_merge.py`
- **OAuth token encryption at rest** (`app/security/crypto.py`)
  - Fernet (AES-128-CBC + HMAC-SHA256) around access / refresh tokens
  - `INTEGRATION_ENCRYPTION_KEY` env for production; auto-derives a stable dev
    key from `JWT_SECRET_KEY` when unset
- **Master Agent parallel dispatch** (`MasterAgent.dispatch_parallel`)
  - `IntentResult.secondary` — LLM classifier can propose extra task types
  - `DispatchResult` — primary + `{task_type → AgentResult}` extras
  - Guarded by `MASTER_PARALLEL_ENABLED`; extras run concurrently via
    `asyncio.create_task`; failing extras are logged and dropped without
    affecting the primary reply
- **Integrations ledger endpoint** — `GET /api/v1/integrations/events` for the
  Chrome side panel to show sync activity
- **Chrome Extension v0.8** (`extension/`)
  - Side Panel (`sidepanel.html/js`) — Profile snapshot + sync events + quick
    capture (requires Chrome ≥ 114)
  - Keyboard shortcut `Alt+Shift+C` opens the extension action
  - Content script now recognises LinkedIn / Boss / Lagou JD pages and GitHub
    PR list pages (adds a "⇆ 拉取我的 PR" button)
  - `chrome.notifications` integration for post-send feedback
  - `sidePanel` + `notifications` added to Manifest V3 permissions
- **Unit tests** (23 new)
  - `tests/test_github_webhook_signature.py` (7) — HMAC verifier happy path +
    missing secret + wrong algo + tamper detection
  - `tests/test_github_extractors.py` (8) — Data Minimizer whitelist, body
    truncation, PR/push → Candidate mapping, `source_ref` format
  - `tests/test_crypto_roundtrip.py` (4) — encrypt/decrypt roundtrip, empty
    passthrough, explicit key precedence, invalid-key fallback
  - `tests/test_master_parallel_dispatch.py` (3) — flag off/on + extra failure
    isolation
  - `tests/test_app_boot.py` — expected endpoint set expanded with the v0.8
    routers

### Changed

- `Candidate` dataclass gained a `source_ref: str | None` field
- Extension `manifest.json` bumped to `0.8.0`; content-script match list now
  covers LinkedIn / zhipin / lagou / GitHub `/pulls`
- Backend FastAPI `title` / `description` mention v0.8 wording

### Migration

- **`0003_v08_oauth_and_sync.py`** (Alembic) adds:
  - `users.github_user_id` (unique) + `users.github_login`
  - `oauth_connections` table (Fernet-encrypted token columns)
  - `sync_events` table with `(provider, external_id)` UNIQUE for idempotency
  - `profile_entries.source_ref` + partial UNIQUE index per
    `(user_id, source_type, source_ref)`

Run: `make migrate` (or `alembic upgrade head` inside `backend/`).

### Environment

New env keys in `backend/.env.example`:

```
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_OAUTH_SCOPES=read:user user:email repo
GITHUB_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/oauth/github/callback
GITHUB_WEBHOOK_SECRET=
GITHUB_API_BASE=https://api.github.com
GITHUB_SYNC_MAX_PRS=30
GITHUB_PR_BODY_MAX_CHARS=500
INTEGRATION_ENCRYPTION_KEY=          # blank in dev → derived from JWT_SECRET_KEY
MASTER_PARALLEL_ENABLED=true
```

### Explicitly out of scope for v0.8

- Kafka / Redis Streams event bus
- Analysis Agent / Job Agent
- Calendar / Jira integrations
- Qdrant swap (pgvector still fits Beta+ data volumes)

## [0.5.0] — Beta

- Master Agent (rule + Haiku fallback)
- Profile Engine v0.5 (Ingester / Merger / ConfidenceScorer / Summarizer +
  pgvector HNSW semantic search)
- Resume Studio (multi-version generation + diagnosis + Markdown/HTML/PDF export)
- JD analysis + matching + Evidence Chain
- Screenshot OCR via Claude Vision
- Chrome extension prototype (Manifest V3)

## [0.1.0] — Alpha

- FastAPI + JWT + Level 0 anonymous generate
- LLM Gateway (Claude + Prompt Cache + token/cost accounting)
- EfficiencyAgent chains: `weekly_report` / `star` / `free_format`
- Whisper voice input, resume upload parsing
- PostgreSQL + Redis + Alembic + rate limiting
