# AI Career Copilot — Backend (v0.1 Alpha)

> AI 职业副驾驶后端服务的 **v0.1 Alpha** 骨架实现。
> 目标：验证 "碎片输入 → 高质量周报" 的核心 Aha Moment。

本目录只包含后端，覆盖了文档 `technical_implementation_guide.md` 第 4 章描述的
v0.1 核心骨架：

- FastAPI 统一服务（异步）
- **Agent Protocol** 预埋（v0.1 单 Agent，v0.5+ 扩展为多 Agent）
- **LLM Gateway**（Claude Sonnet + Prompt Cache + Token/Cost 计量）
- **EfficiencyAgent** 三个 Chain：`weekly_report` / `star` / `free_format`
- **语音输入**（Whisper → 复用生成链路，SSE 返回 transcript + 内容）
- **简历上传解析**（PDF / DOCX / TXT → LLM 结构化 → 落库 profiles）
- SSE 流式生成端点 `/api/v1/generate` `/api/v1/generate/voice`
- JWT 认证 + Level 0 匿名生成
- PostgreSQL + Redis + Alembic 迁移

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
│   │   ├── logging_config.py    structlog
│   │   ├── api/v1/              路由 (auth / generate / history / meta)
│   │   ├── api/middleware/      请求 ID 中间件
│   │   ├── agents/              Agent Protocol + EfficiencyAgent
│   │   ├── llm/                 LLM Gateway
│   │   ├── models/              ORM + Pydantic schemas
│   │   ├── repository/          数据访问层
│   │   └── services/            业务服务 (auth / generate)
│   ├── prompts/                 YAML prompt 模板
│   ├── migrations/              Alembic
│   ├── tests/                   pytest 冒烟
│   ├── pyproject.toml
│   └── .env.example
├── infra/
│   └── docker/
│       ├── docker-compose.yml   Postgres + Redis
│       └── Dockerfile.backend
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
| `OPENAI_API_KEY` | OpenAI Key，用于 Whisper 语音端点（不用语音功能可留空） |
| `LLM_DEFAULT_MODEL` | 默认 `claude-sonnet-4-5`，也可换 `claude-sonnet-4-6` 等 |
| `WHISPER_MODEL` | 默认 `whisper-1` |
| `WHISPER_LANGUAGE` | ISO-639-1，默认 `zh`；留空则自动检测 |
| `JWT_SECRET_KEY` | 生产环境请用 `openssl rand -hex 32` 生成 32-byte hex |
| `DATABASE_URL` | 默认指向 compose 内的 Postgres；docker 模式会被 compose override |
| `REDIS_URL` | 同上 |
| `DOCUMENT_MAX_UPLOAD_BYTES` | 简历/音频上传大小上限（默认 10 MB） |
| `DOCUMENT_MAX_CHARS` | 简历文本送 LLM 前的截断上限（默认 20k） |
| `RATE_LIMIT_ANON_PER_HOUR` / `RATE_LIMIT_USER_PER_HOUR` | 匿名 / 已登录用户配额 |

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

## 已实现 vs 待实现（v0.1 完整 spec 对照）

| 功能 | 状态 | 说明 |
|---|---|---|
| 文本输入 → 周报生成 | ✅ | `/api/v1/generate` |
| STAR / 自由格式 | ✅ | `task_type` 切换 |
| SSE 流式输出 | ✅ | 3 种 event: `message` / `done` / `error` |
| Level 0 匿名 | ✅ | 不带 Authorization 即可调用 |
| 注册 / 登录 (email) | ✅ | JWT (HS256) |
| 历史记录 | ✅ | `/api/v1/history` |
| Prompt Cache | ✅ | 系统 prompt `cache_control: ephemeral` |
| 语音输入（Whisper） | ✅ | `/api/v1/generate/voice`，支持 mp3/m4a/wav/webm 等 |
| 简历上传解析 | ✅ | `/api/v1/profile/resume` (PDF / DOCX / TXT) |
| 用户反馈（评分 + 编辑） | ✅ | `PATCH /api/v1/history/{id}`，自动计算 `edit_ratio` |
| 无记忆模式切换 | ✅ | `GET/PATCH /api/v1/settings`，`full`/`selective`/`none` |
| 频率限制 | ✅ | Redis 固定窗口：匿名 5/h、登录 60/h（Redis 失效时 fail-open） |
| 结构化副产品提取 | ✅ | 生成后异步写入 `extracted_data`（`memory_mode=full` 才提取） |
| 简历原文 S3 存储 | ⏳ | v0.1 只落结构化字段，`raw_resume_url` 待 v0.5 |
| Landing Page / 工作台 | ⏳ | 前端未启动（本轮范围仅后端骨架） |

---

## 关键设计说明

### Agent Protocol（预埋抽象）

`app/agents/base.py` 定义了 `BaseAgent` + `AgentRouter`：

- v0.1 只有一个 Agent (`EfficiencyAgent`)，路由是硬编码规则。
- v0.5 将把 `AgentRouter` 升级为 Master Agent（Rule → Haiku fallback 二段意图分类），
  接口不变，`GenerateService` 无需改造。

### LLM Gateway（唯一 LLM 入口）

`app/llm/gateway.py` 是 **所有 LLM 调用的必经之路**（架构红线 #4）：

- Prompt Cache 从 v0.1 开启（`cache_control: ephemeral`）。
- Token 计量 + 成本追踪（含 cache read / cache creation 精细拆分）。
- 支持 `generate()`（阻塞）和 `stream()` / `stream_with_usage()`（流式，含 usage 回调）。
- 定价表覆盖 Sonnet 4.x / Haiku 4.5 / Opus 4.6，模型前缀匹配。

### 降级 / 未来演进

- **Profile Engine**：v0.1 只落库到 `generations` + `extracted_data`；v0.5 引入
  ingester / merger / summarizer / pgvector。
- **Redis Streams**：v0.1 未使用；v1.0 引入事件总线。
- **Master Agent**：v0.5 上线；v0.1 路由是纯规则。

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
make db-up         # 只启动 Postgres+Redis
make migrate       # 应用迁移（本地 venv）
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
| **v0.1 Alpha** | 核心 Aha 验证（本骨架） | PG / Redis / S3 |
| v0.3 Alpha+ | 录入习惯养成 | (0 新组件) |
| v0.5 Beta | 简历价值验证 | pgvector + Celery |
| v0.8 Beta+ | 数据飞轮启动 | Qdrant (条件) + OAuth |
| v1.0 GA | 留存闭环 | Redis Streams |
| v1.5 Pro | 付费验证 | Stripe + 对话引擎 |
| v2.0 Scale | 规模化 | Neo4j + Kafka + i18n |

详细规划见 `~/doc/agent/doc/PMO_review_and_restructure.md`。
