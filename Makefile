# AI Career Copilot — Makefile
# 主要用于 v0.1 Alpha 阶段的本地开发流程。

BACKEND := backend
COMPOSE := docker compose -f infra/docker/docker-compose.yml

.PHONY: help
help:
	@echo "Local dev (venv):"
	@echo "  make venv            创建 backend/.venv"
	@echo "  make install         pip install -e '.[dev]' (需已激活 venv)"
	@echo "  make db-up           只启动 Postgres + Redis (给本地 venv 用)"
	@echo "  make db-down         停止 Postgres + Redis"
	@echo "  make db-logs         跟踪数据库日志"
	@echo "  make migrate         运行 Alembic 迁移 (venv)"
	@echo "  make dev             启动 uvicorn 开发服务 (自动 reload)"
	@echo "  make lint / format / test / smoke"
	@echo ""
	@echo "Full docker stack (一键跑通，另一台机器也用这个):"
	@echo "  make up              build + 起 pg/redis/migrate/backend"
	@echo "  make down            停整个栈"
	@echo "  make nuke            停栈并删数据卷 (慎用)"
	@echo "  make build           只 build backend 镜像"
	@echo "  make logs            跟随 backend 日志"
	@echo "  make ps              查看所有服务状态"

.PHONY: venv
venv:
	python3.11 -m venv $(BACKEND)/.venv
	@echo "→ 激活: source $(BACKEND)/.venv/bin/activate"

.PHONY: install
install:
	cd $(BACKEND) && pip install -e ".[dev]"

.PHONY: db-up
db-up:
	$(COMPOSE) up -d postgres redis
	@echo "→ Postgres localhost:5432 (career/career/career_copilot)"
	@echo "→ Redis    localhost:6379"

.PHONY: db-down
db-down:
	$(COMPOSE) stop postgres redis

.PHONY: db-nuke
db-nuke:
	$(COMPOSE) down -v

.PHONY: db-logs
db-logs:
	$(COMPOSE) logs -f postgres

# ---- Full docker stack (recommended for fresh machines) ----

.PHONY: build
build:
	$(COMPOSE) build backend

.PHONY: up
up:
	@test -f backend/.env || (echo "缺少 backend/.env，请先 cp backend/.env.example backend/.env 并填 ANTHROPIC_API_KEY" && exit 1)
	$(COMPOSE) up -d --build

.PHONY: down
down:
	$(COMPOSE) down

.PHONY: nuke
nuke:
	$(COMPOSE) down -v

.PHONY: logs
logs:
	$(COMPOSE) logs -f backend

.PHONY: ps
ps:
	$(COMPOSE) ps

.PHONY: migrate
migrate:
	cd $(BACKEND) && alembic upgrade head

.PHONY: migrate-down
migrate-down:
	cd $(BACKEND) && alembic downgrade -1

.PHONY: dev
dev:
	cd $(BACKEND) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: run
run:
	cd $(BACKEND) && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2

.PHONY: lint
lint:
	cd $(BACKEND) && ruff check app tests

.PHONY: format
format:
	cd $(BACKEND) && ruff format app tests
	cd $(BACKEND) && ruff check --fix app tests

.PHONY: test
test:
	cd $(BACKEND) && pytest -v

.PHONY: smoke
smoke:
	@echo "== /health =="
	@curl -sS http://localhost:8000/health | jq . || curl -sS http://localhost:8000/health
	@echo "\n== /api/v1/generate (anonymous, weekly_report) =="
	@curl -sSN -X POST http://localhost:8000/api/v1/generate \
	  -H 'Content-Type: application/json' \
	  -d '{"task_type":"weekly_report","input_content":"这周做了三件事：1) 上线了新的推荐算法；2) 修复了一个用户投诉最多的 Bug；3) 帮同事 review 了两个 PR。"}' \
	  | head -c 2048
	@echo "\n"
