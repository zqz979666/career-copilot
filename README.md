# AI Career Copilot — Backend (v0.8 Beta+)

> AI 职业副驾驶后端服务的 **v0.8 Beta+** 实现。
> 双尖刺（成果录入 + 简历生成）之上启动 **数据飞轮**：GitHub OAuth / Webhook
> 拉入第三方经历，Master Agent 支持并行分发，Profile Engine 多源汇入 + 幂等。

本仓库包含后端服务 + Chrome 扩展，覆盖 `v0.8_beta_plus_spec.md` 增量：

**v0.1 → v0.5 基础（延续）**
- FastAPI 统一异步服务、JWT 认证 + Level 0 匿名生成
- **LLM Gateway**（Claude + Prompt Cache + Token/Cost 计量 + 流式/阻塞/Vision）
- **Master Agent v0.5**：二段意图分类（Rule → Haiku fallback）→ Efficiency / Resume
- **Profile Engine v0.5**：Ingester → Merger → ConfidenceScorer → Summarizer + pgvector 语义检索
- **Resume Studio + JD 分析 + Evidence Chain**、语音（Whisper）、截图（Vision）、Chrome 扩展 v0.5

**v0.8 新增**
- **GitHub OAuth + Webhook**（`app/integrations/github.py`）：`read:user user:email repo`
  最小 scope；HMAC-SHA256 常量时间校验；`X-Hub-Signature-256` 失败即 401。
- **Data Minimizer**：PR/Push 事件只保留 `title / body[:500] / repo / merged` 等白名单字段，
  丢弃 diff / review_comments / reviewers / 文件列表。
- **OAuth 令牌加密存储**（`app/security/crypto.py`）：Fernet（AES-128-CBC + HMAC-SHA256）
  写入 `oauth_connections.access_token_encrypted`；`INTEGRATION_ENCRYPTION_KEY` 未设置时
  仅在开发环境下从 `JWT_SECRET_KEY` 派生一把 dev 密钥。
- **Profile Engine v0.8**：`ingest_third_party()` 走同一 Merger；`profile_entries.source_ref`
  作为第三方幂等键（`github:pr:{node_id}` / `github:repo:{name}`）——同一 PR 重放
  **不**累加 `occurrences`，避免置信度虚增。
- **GitHubSyncService**：手动同步 + Webhook 幂等入账 ledger（`sync_events (provider, external_id)` UNIQUE）。
- **Master Agent 并行分发**：`dispatch_parallel()` 由 `MASTER_PARALLEL_ENABLED` 开关，
  extras 用 `asyncio.create_task` 并发跑，失败静默降级；primary 结果永远返回。
- **Chrome 扩展 v0.8**：Side Panel（Chrome ≥ 114）+ 快捷键 `Alt+Shift+C` + GitHub PR 列表页
  「⇆ 拉取我的 PR」+ 通知（`chrome.notifications`）。

---

## 目录结构

```
career-copilot/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI 入口 + lifespan 装配
│   │   ├── config.py            pydantic-settings 配置
│   │   ├── db.py                SQLAlchemy async engine / session
│   │   ├── dependencies.py      FastAPI DI wiring
│   │   ├── api/v1/              路由 (auth/generate/history/profile/resumes/jd/settings)
│   │   ├── api/middleware/      请求 ID / 频率限制 中间件
│   │   ├── agents/              Master + Efficiency + Resume Agent
│   │   ├── llm/                 LLM Gateway(+Vision) / Embeddings / json_utils
│   │   ├── models/              ORM + Pydantic schemas
│   │   ├── repository/          数据访问层 (profile_entry / resume / jd / evidence ...)
│   │   └── services/            业务服务 (generate / profile_engine / resume_studio / jd ...)
│   ├── prompts/                 YAML prompt 模板 (周报/月报/晋升/PR/JD/简历...)
│   ├── migrations/              Alembic (0001 initial + 0002 v0.5 pgvector)
│   ├── tests/                   pytest 单元测试
│   ├── pyproject.toml           含可选 [pdf] 组 (WeasyPrint)
│   └── .env.example
├── extension/                   Chrome 扩展原型 (Manifest V3)
│   ├── manifest.json  background.js  content.js
│   ├── popup.html/js  options.html/js  README.md
├── infra/
│   └── docker/
│       ├── docker-compose.yml   pgvector/pgvector:pg15 + Redis + migrate + backend
│       └── Dockerfile.backend   含 WeasyPrint 系统库 + fonts-noto-cjk
├── Makefile
└── .gitignore
```

---

## 启动步骤

### 方式 A：一键 Docker（推荐，另一台机器也用这个）

需要 Docker Desktop（含 `docker compose`）。**不需要**本地 Python。

```bash
git clone git@github.com:zqz979666/career-copilot.git
cd career-copilot

# 1. 准备 env
cp backend/.env.example backend/.env
# 编辑 backend/.env，至少填入 ANTHROPIC_API_KEY

# 2. 一键起 pg + redis + migrate + backend
make up            # 等价于 docker compose -f infra/docker/docker-compose.yml up -d --build
make logs          # 跟随 backend 日志，看到 "Uvicorn running" 即 OK
curl http://localhost:8000/health
```

停止 / 清理：

```bash
make down          # 停容器，保留数据卷
make nuke          # 停容器 + 删除 pg/redis 数据卷（慎用）
```

`docker-compose.yml` 内含四个服务：`postgres` / `redis` / `migrate`（一次性
跑 `alembic upgrade head` 后退出）/ `backend`。`backend` 通过
`depends_on.condition: service_completed_successfully` 等 `migrate` 成功后再启动。

### 方式 B：本地 Python venv（开发热 reload）

需要 Python 3.11+：

```bash
cd career-copilot
make venv
source backend/.venv/bin/activate
make install

cp backend/.env.example backend/.env
# 编辑 backend/.env

make db-up         # 只起 Postgres + Redis
make migrate       # 应用迁移
make dev           # uvicorn --reload
# → http://localhost:8000
# → http://localhost:8000/docs (Swagger UI)
```

### 环境变量

| Key | 说明 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API Key，必须填写（https://console.anthropic.com） |
| `OPENAI_API_KEY` | OpenAI Key，用于 Whisper 语音 **+ Profile embeddings**（留空则语义检索降级为关键词/时间序） |
| `LLM_DEFAULT_MODEL` | 默认 `claude-sonnet-4-5` |
| `LLM_INTENT_MODEL` | Master Agent 意图分类兜底模型，默认 `claude-haiku-4-5` |
| `VISION_MODEL` | 截图 OCR 模型，默认 `claude-sonnet-4-5` |
| `EMBEDDING_ENABLED` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | pgvector 语义检索；默认 `text-embedding-3-small` (1536) |
| `RESUME_MAX_VERSIONS` / `RESUME_RETRIEVAL_TOP_K` | 简历版本上限 / 送 Resume Agent 的 Profile 条目数 |
| `WHISPER_MODEL` / `WHISPER_LANGUAGE` | 默认 `whisper-1` / `zh`（留空自动检测） |
| `JWT_SECRET_KEY` | 生产环境请用 `openssl rand -hex 32` 生成 32-byte hex |
| `DATABASE_URL` / `REDIS_URL` | 默认指向本地；docker 模式会被 compose override 为服务名 |
| `DOCUMENT_MAX_UPLOAD_BYTES` / `DOCUMENT_MAX_CHARS` | 上传大小上限（默认 10 MB）/ 送 LLM 截断上限（默认 20k） |
| `RATE_LIMIT_ANON_PER_HOUR` / `RATE_LIMIT_USER_PER_HOUR` | 匿名 / 已登录用户配额 |
| **v0.8** `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth App 凭据；留空则 OAuth 端点返回 503 |
| **v0.8** `GITHUB_OAUTH_SCOPES` | 默认 `read:user user:email repo`；仅公共 PR 可改为 `... public_repo` |
| **v0.8** `GITHUB_OAUTH_REDIRECT_URI` | OAuth 回调 URL，需与 GitHub App 后台一致 |
| **v0.8** `GITHUB_WEBHOOK_SECRET` | Webhook HMAC 校验密钥；留空则所有 webhook 一律 401 |
| **v0.8** `GITHUB_SYNC_MAX_PRS` / `GITHUB_PR_BODY_MAX_CHARS` | 手动同步 PR 上限（默认 30）/ PR body 截断（默认 500） |
| **v0.8** `INTEGRATION_ENCRYPTION_KEY` | Fernet key（`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`）；留空开发环境自动从 `JWT_SECRET_KEY` 派生 |
| **v0.8** `MASTER_PARALLEL_ENABLED` | Master Agent 并行分发开关；默认 `true` |

> **PDF 导出**：`WeasyPrint` 依赖系统库（pango/cairo），单列为可选组。本地
> `make install-pdf` 安装 `.[dev,pdf]`；docker 镜像已内置系统库 + 中文字体。
> 未安装时简历导出端点自动降级为 HTML / Markdown。

> 注意：`backend/.env` 里的 `DATABASE_URL` / `REDIS_URL` 是给**本地 venv**用的
> （`localhost:5432` / `localhost:6379`）。docker 模式下 compose 会用服务名覆盖成
> `postgres` / `redis`，两种模式无需切换 env 文件。

---

## 端到端手测

**匿名生成（Level 0）**：

```bash
curl -N -X POST http://localhost:8000/api/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "task_type": "weekly_report",
    "input_content": "这周做了三件事：1) 上线了新的推荐算法；2) 修复了一个用户投诉最多的 Bug；3) 帮同事 review 了两个 PR。"
  }'
```

响应是 SSE 流（`data` 字段是 JSON 编码的字符串，前端 `JSON.parse` 即可）：

```
event: message
data: "## 本周工作总结"

event: message
data: "\n\n### 推荐系统"
...
event: done
data: {"status": "complete"}
```

**注册 → 登录 → 生成 → 历史**：

```bash
# 注册（返回 JWT）
TOKEN=$(curl -sS -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"secret123","name":"Demo"}' \
  | jq -r .access_token)

# STAR 格式
curl -N -X POST http://localhost:8000/api/v1/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"task_type":"star","input_content":"我在 Q2 主导了订单中心的分库分表改造，最终 QPS 从 3k 提升到 12k，慢查询下降 80%"}'

# 历史记录
curl -sS http://localhost:8000/api/v1/history \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**语音输入（Whisper）**：

```bash
# 支持格式: mp3 / m4a / wav / webm / mp4 / mpga / mpeg
curl -N -X POST http://localhost:8000/api/v1/generate/voice \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@my_report.m4a" \
  -F "task_type=weekly_report" \
  -F "language=zh"
```

响应比文本端点多一个前置 `transcript` 事件：

```
event: transcript
data: {"text": "这周我做了三件事..."}

event: message
data: "## 本周工作总结"
...
event: done
data: {"status": "complete"}
```

**简历上传解析（PDF / DOCX / TXT）**：

```bash
# 上传简历（需登录）
curl -sS -X POST http://localhost:8000/api/v1/profile/resume \
  -H "Authorization: Bearer $TOKEN" \
  -F "resume=@my_resume.pdf" | jq .

# 查看解析后的 Profile
curl -sS http://localhost:8000/api/v1/profile \
  -H "Authorization: Bearer $TOKEN" | jq .
```

返回示例（截取）：

```json
{
  "profile": {
    "id": "...", "user_id": "...", "version": 1,
    "basic_info": {
      "name": "张三", "email": "zhang@example.com",
      "headline": "5 年后端工程师，专注分布式系统",
      "years_of_experience": 5
    },
    "skills": ["Java", "Spring", "Kafka", "PostgreSQL", "Redis"],
    "experiences": [
      {
        "company": "字节跳动", "title": "高级后端工程师",
        "start_date": "2023-03", "end_date": "present",
        "bullets": ["主导订单中心分库分表", "..."]
      }
    ]
  },
  "source_format": "pdf",
  "source_page_count": 2,
  "source_chars": 4820,
  "extracted_fields": 4,
  "token_usage": {"input_tokens": 1420, "output_tokens": 610, "cost_usd": 0.013}
}
```

**用户反馈（评分 + 编辑后文本）**：

```bash
# GEN_ID 通过 /api/v1/history 得到
curl -sS -X PATCH http://localhost:8000/api/v1/history/$GEN_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "user_rating": 5,
    "edited_text": "## 本周工作总结\n\n### 推荐系统\n- 灰度上线新推荐算法，A/B 实验显示 CTR +3.2%\n..."
  }' | jq .
```

响应返回更新后的记录，其中 `edit_ratio` 由服务端根据原始 `output_text` 与 `edited_text` 自动计算（越大代表用户改动越大）。

**记忆模式切换**：

```bash
# 查询当前设置
curl -sS http://localhost:8000/api/v1/settings \
  -H "Authorization: Bearer $TOKEN" | jq .

# 关闭记录（不落 generations、不做副产品提取）
curl -sS -X PATCH http://localhost:8000/api/v1/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"memory_mode":"none"}' | jq .
```

| memory_mode | 生成落库 | 结构化副产品提取 |
|---|---|---|
| `full` (默认) | ✅ | ✅ |
| `selective` | ✅ | ❌ |
| `none` | ❌ | ❌ |

---

## v0.5 端到端手测（双尖刺）

以下均需登录（`TOKEN` 见上文注册流程）。

**① 意图识别（Master Agent）**：

```bash
curl -sS -X POST http://localhost:8000/api/v1/intent \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"task_type":"auto","input_content":"帮我把这季度的工作整理成晋升材料"}' | jq .
# → {"intent":"promotion","task_type":"promotion","agent_type":"efficiency","method":"rule",...}
```

**② 工作成果录入（auto 自动路由 + Profile 累积）**：

```bash
# task_type=auto 让 Master Agent 决定用哪条链；生成后异步 ingest 到 Profile Engine
curl -N -X POST http://localhost:8000/api/v1/generate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"task_type":"auto","input_content":"这个月主导了支付网关重构，P99 从 800ms 降到 120ms，接入 5 个业务方"}'

# 触发 Profile 重编译后，查看快照 / 条目
curl -sS -X POST http://localhost:8000/api/v1/profile/rebuild -H "Authorization: Bearer $TOKEN" | jq .
curl -sS http://localhost:8000/api/v1/profile/snapshot -H "Authorization: Bearer $TOKEN" | jq .
curl -sS http://localhost:8000/api/v1/profile/entries -H "Authorization: Bearer $TOKEN" | jq .
```

**③ 截图解析（Vision OCR）**：

```bash
curl -sS -X POST http://localhost:8000/api/v1/profile/screenshot \
  -H "Authorization: Bearer $TOKEN" -F "image=@dashboard.png" | jq .
```

**④ JD 分析 + 匹配（Evidence Chain）**：

```bash
curl -sS -X POST http://localhost:8000/api/v1/jd/analyze \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jd_text":"资深后端工程师，要求精通分布式、高并发，有支付/交易系统经验...","with_matching":true}' | jq .
# → analysis(要求拆解) + matching(逐项匹配 + evidence_chain + overall_score)
```

**⑤ 简历生成 / 管理 / 诊断 / 导出**：

```bash
# 基于 Profile（可选绑定某次 JD 分析做定向优化）生成一版简历
RID=$(curl -sS -X POST http://localhost:8000/api/v1/resumes \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"后端-字节版","target_jd":"资深后端工程师..."}' | jq -r .id)

curl -sS http://localhost:8000/api/v1/resumes -H "Authorization: Bearer $TOKEN" | jq .            # 列表
curl -sS -X POST http://localhost:8000/api/v1/resumes/diagnose \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"resume_id\":\"$RID\"}" | jq .                                                            # 诊断

# 导出（format=md|html|pdf；未装 WeasyPrint 时 pdf 自动降级）
curl -sS "http://localhost:8000/api/v1/resumes/$RID/export?format=md" -H "Authorization: Bearer $TOKEN"
curl -sS "http://localhost:8000/api/v1/resumes/$RID/export?format=pdf" -H "Authorization: Bearer $TOKEN" -o resume.pdf
```

**⑥ Chrome 扩展**：见 `extension/README.md`（`chrome://extensions` → 开发者模式 → 加载 `extension/` 目录）。

---

## v0.8 端到端手测（GitHub 数据飞轮）

前置：在 GitHub → Settings → Developer settings → OAuth Apps 注册一个 App，
`Authorization callback URL` 填 `http://localhost:8000/api/v1/oauth/github/callback`，
把 Client ID / Secret 填入 `backend/.env`，重启后端。

**① 授权 → 回调**：

```bash
# 浏览器打开（需要登录态 cookie / bearer）
open "http://localhost:8000/api/v1/oauth/github/authorize" \
  # 前端一般拿到 authorize_url 后再跳
```

`GET /api/v1/oauth/github/authorize` 返回 `{provider, authorize_url, state}` 并写入
两条 HttpOnly cookie（`oauth_state` / `oauth_uid`，`SameSite=Lax`，10 分钟过期）。
GitHub 授权完跳回 `/callback`，服务端校验 state → 交换 code → Fernet 加密 access_token
写入 `oauth_connections`。

**② 手动同步 PR**：

```bash
curl -sS -X POST http://localhost:8000/api/v1/oauth/github/sync \
  -H "Authorization: Bearer $TOKEN" | jq .
# → {"fetched":27,"created":24,"updated":3,"skipped_duplicates":0}
```

- `fetched`：从 GitHub 拉到的 PR 数
- `created` / `updated`：Profile 新增 / 更新的条目
- `skipped_duplicates`：`sync_events` ledger 已存在的重复投递

**③ Webhook 落库**（GitHub → Repo → Settings → Webhooks 配置 `POST /api/v1/webhooks/github`，
Content type `application/json`，Secret = `GITHUB_WEBHOOK_SECRET`；关注 `pull_request` / `push`）。

**④ 查看同步事件流水**：

```bash
curl -sS "http://localhost:8000/api/v1/integrations/events?limit=20" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**⑤ 解除绑定**：

```bash
curl -sS -X DELETE http://localhost:8000/api/v1/oauth/github \
  -H "Authorization: Bearer $TOKEN" -o /dev/null -w "%{http_code}\n"
# → 204
```

---

## 已实现 vs 待实现（v0.5 spec 对照）

| 功能 | 状态 | 说明 |
|---|---|---|
| 文本 → 周报 / STAR / 自由格式 | ✅ | `/api/v1/generate`，SSE 流式 |
| 月报 / 晋升 / PR 解析 / 会议解析 | ✅ | v0.5 新增 EfficiencyAgent 链 |
| Master Agent 意图分类 | ✅ | `/api/v1/intent`，Rule → Haiku fallback；`task_type=auto` 自动路由 |
| 语音输入（Whisper） | ✅ | `/api/v1/generate/voice` |
| 截图解析（Vision OCR） | ✅ | `/api/v1/profile/screenshot` |
| 简历上传解析 | ✅ | `/api/v1/profile/resume`，并 seed 到 Profile Engine |
| **Profile Engine v0.5** | ✅ | Ingester/Merger/ConfidenceScorer/Summarizer + pgvector 语义检索 |
| Profile 快照 / 条目管理 / 确认 | ✅ | `/api/v1/profile/snapshot` `entries` `entries/confirm` `rebuild` `export` |
| **简历生成 / 多版本管理** | ✅ | `/api/v1/resumes`（生成/列表/取/改/删），上限 `RESUME_MAX_VERSIONS` |
| 简历诊断 | ✅ | `/api/v1/resumes/diagnose` |
| 简历导出 MD / HTML / PDF | ✅ | `/api/v1/resumes/{id}/export`；PDF 走 WeasyPrint（可选，缺失则降级） |
| **JD 分析 + 匹配 + Evidence Chain** | ✅ | `/api/v1/jd/analyze`（数据依据/推理/置信度/建议） |
| 注册 / 登录 / 历史 / 反馈 / 记忆模式 | ✅ | 延续 v0.1 |
| 频率限制 | ✅ | Redis 固定窗口（fail-open） |
| Prompt Cache / Token & Cost 计量 | ✅ | LLM Gateway 统一入口 |
| Chrome 扩展原型 | ✅ | `extension/`（Manifest V3） |
| **GitHub OAuth + Webhook**（v0.8） | ✅ | `/api/v1/oauth/github/*`、`/api/v1/webhooks/github`；Fernet 加密令牌；HMAC 校验 |
| **Profile 多源汇入 + 幂等**（v0.8） | ✅ | `source_ref = github:pr:{node_id}`；`sync_events (provider, external_id)` UNIQUE |
| **Master Agent 并行分发**（v0.8） | ✅ | `MASTER_PARALLEL_ENABLED`；`dispatch_parallel(primary, extras)` |
| **Chrome 扩展 v0.8**（Side Panel + GitHub 同步） | ✅ | `extension/sidepanel.html/js`、`Alt+Shift+C` 快捷键、通知 |
| Landing Page / Web 工作台 | ⏳ | 本轮范围为后端 + 扩展；Web 前端后续版本 |
| 简历原文对象存储 | ⏳ | 当前落结构化字段 + Evidence 原文入库，S3 待接入 |

---

## 关键设计说明

### Master Agent（v0.5 编排）

`app/agents/master.py` 取代 v0.1 的硬编码 `AgentRouter`：

- **二段意图分类**：先走规则表（关键词/正则，零成本、可预测），命中即返回；
  未命中才 fallback 到 Haiku（`LLM_INTENT_MODEL`）做结构化分类。
- 路由到 `EfficiencyAgent`（录入/改写，流式）或 `ResumeAgent`（简历/JD，阻塞 JSON）。
- `task_type=auto` 时由 `GenerateService.resolve_intent` 调用分类；接口对上层透明。

### Profile Engine v0.5（数据通道）

`app/services/profile_engine.py` + `profile_merge.py`（纯逻辑，便于单测）：

- **Ingester**：消费 `extracted_data`（生成副产品）+ 简历 seed，转成候选条目。
- **Merger**：`dedup_key` 实体对齐去重，重复出现累加 `occurrences`。
- **ConfidenceScorer**：按来源类型/出现次数打分，低分条目走人工确认。
- **Summarizer + Snapshot**：编译成 `profile.snapshot`（结构化）+ `summary`（供 prompt 注入）。
- **语义检索**：`profile_entries.embedding`（pgvector, HNSW 索引）+ OpenAI embeddings；
  无 key 时降级为关键词/时间序检索，写 NULL 向量。

### Evidence Chain（v0.5 诚实护栏）

`app/services/evidence.py`：JD 匹配的每一项都附带 **数据依据 / 推理 / 置信度 / 建议**，
并做 honesty guard（无依据不虚构），`overall_score` / `summarize_gaps` 汇总差距。

### LLM Gateway（唯一 LLM 入口）

`app/llm/gateway.py` 是 **所有 LLM 调用的必经之路**（架构红线 #4）：

- Prompt Cache（`cache_control: ephemeral`）+ Token/Cost 计量（cache read/creation 拆分）。
- `generate()`（阻塞）/ `stream()` / `stream_with_usage()`（流式）/ `generate_vision()`（多模态截图）。
- 定价表覆盖 Sonnet 4.x / Haiku 4.5 / Opus 4.6，模型前缀匹配。

### 技术基线取舍（对齐 PMO review）

- **pgvector 而非 Qdrant**：v0.5 数据量下 pgvector 足够，少一个组件、复用 PG 事务。
- **asyncio 后台任务而非 Celery**：`generate → extract → ingest` 用 fire-and-forget
  `asyncio.create_task`，够用且可测；重任务队列留待后续版本。
- **WeasyPrint 可选**：PDF 依赖系统库，单列 `[pdf]` 组，缺失时导出降级为 HTML/MD。

### v0.8 GitHub OAuth + Webhook（数据飞轮）

`app/integrations/github.py` + `app/services/{oauth_service,github_sync_service}.py`：

- **OAuth 握手**：`GET /authorize` 用 `secrets.token_urlsafe(24)` 生成 CSRF state，
  同时写 HttpOnly `oauth_state` + `oauth_uid` cookie（`SameSite=Lax`, 10 分钟）。
  回调校验 state 一致 → 交换 code → `GitHubClient.get_user` → 更新 `users.github_*` +
  upsert `oauth_connections`。防跨账户抢注：同一 `github_user_id` 已绑定其他账号即拒绝。
- **令牌加密**（`app/security/crypto.py`）：Fernet（AES-128-CBC + HMAC-SHA256）
  写入 `oauth_connections.access_token_encrypted`；`INTEGRATION_ENCRYPTION_KEY` 未设置
  会从 `JWT_SECRET_KEY` 派生一把 dev key，方便本地调试。生产必须显式设置。
- **Webhook HMAC**（`verify_webhook_signature`）：`X-Hub-Signature-256` 头 → `hmac.compare_digest`
  常量时间校验；密钥缺失 / 算法前缀不是 `sha256` / body 被篡改 → 一律 401。
- **Data Minimizer**（`extract_pr_minimal` / `extract_push_minimal`）：仅保留白名单字段
  （`title`, `body[:500]`, `repo_full_name`, `merged`, ...），丢弃 diff / review_comments /
  reviewers / 文件列表。commit 只留 message 首行。
- **幂等 ledger**：`sync_events (provider, external_id)` UNIQUE + `profile_entries.source_ref`
  UNIQUE per (user, source_type)。Webhook 重投 / 手动 re-sync 会命中同一行更新内容，
  **不**累加 `occurrences`（避免置信度虚增）。

### v0.8 Master Agent 并行分发

`MasterAgent.dispatch_parallel(context, extras_task_types)`：

- 由 `MASTER_PARALLEL_ENABLED` 一刀切控制；关闭后行为完全退回单 Agent。
- Primary 与 extras 通过 `asyncio.create_task` 并发；extras 失败（含 `NotImplementedError`）
  静默丢弃，**永远**不影响 primary 的返回。用于「帮我写周报同时把这次经历加进简历」
  这类可自然并行的复合意图。

### 频率限制（Redis 固定窗口）

`app/api/middleware/rate_limit.py` 提供了一个针对 `/api/v1/generate*` 的
简单 fixed-window 计数器：

- 匿名请求按客户端 IP 计数（先看 `X-Forwarded-For` 首跳，退回 `Request.client.host`）
- 已登录请求按 `user_id` 计数（Bearer token 解码；解码失败自动降级为匿名）
- Key: `ratelimit:{scope}:{identity}:{hour_bucket}`；TTL 3600s
- 命中限制返回 429，并携带 `Retry-After` / `X-RateLimit-*` header
- **Redis 不可用时 fail-open**：Alpha 阶段宁可放过合法流量也不制造事故

配额通过 env 调整（`RATE_LIMIT_ANON_PER_HOUR` / `RATE_LIMIT_USER_PER_HOUR`）。

### 结构化副产品提取

`app/services/extraction_service.py` 在 SSE 响应结束后 fire-and-forget 触发一次
低配 LLM 调用（`temperature=0, max_tokens=1024`），从"用户输入 + AI 生成稿"里抽出：

- `project` — 项目名/角色/摘要
- `skill` — 技能标签
- `achievement` — 量化成果摘要
- `tech_stack` — 技术栈关键词

每条以 `status='auto'` 写入 `extracted_data`，v0.5 Profile Engine 的
Merger 会消费这批数据。**仅在 `memory_mode=full` 时启用**；失败会记录 warning
并静默丢弃，绝不阻塞用户可见链路。

---

## 常用命令

```bash
# --- Docker 一键栈 ---
make up            # build + 起 pg/redis/migrate/backend
make down          # 停容器（保留数据卷）
make nuke          # 停容器 + 删数据卷
make logs          # 跟随 backend 日志
make ps            # 服务状态

# --- 本地 venv 模式 ---
make install       # pip install -e '.[dev]'
make install-pdf   # pip install -e '.[dev,pdf]' (含 WeasyPrint，需系统库)
make db-up         # 只启动 Postgres+Redis
make migrate       # 应用迁移（本地 venv，含 0002 pgvector）
make dev           # 开发模式启动（reload）
make lint          # ruff 检查
make format        # ruff 自动修复
make test          # pytest
make smoke         # /health + 一次匿名生成
make db-down       # 关闭依赖
make db-nuke       # 关闭并删除数据卷（慎用）
```

---

## 版本路线图

| 版本 | 里程碑 | 关键新组件 |
|---|---|---|
| v0.1 Alpha | 核心 Aha 验证 | PG / Redis / S3 |
| v0.3 Alpha+ | 录入习惯养成 | (0 新组件) |
| v0.5 Beta | 双尖刺：成果录入 + 简历生成 | pgvector + Vision + 扩展 |
| **v0.8 Beta+（本版本）** | 数据飞轮启动 | GitHub OAuth + Webhook + Fernet + 并行 Master |
| v1.0 GA | 留存闭环 | Redis Streams |
| v1.5 Pro | 付费验证 | Stripe + 对话引擎 |
| v2.0 Scale | 规模化 | Neo4j + Kafka + i18n |

详细规划见 `~/doc/agent/doc/PMO_review_and_restructure.md`。
