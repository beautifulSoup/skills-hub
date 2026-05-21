# skills-hub Makefile (root level)
#
# 使用：make help
#
# Compose 文件在 deploy/，pytest / uv 在 src/ 跑。
# 此 Makefile 屏蔽这些路径细节，对外仍是简洁命令。

SHELL := /bin/bash
COMPOSE := docker compose -f deploy/docker-compose.yml
# dev：叠加源码挂载覆盖 + 默认全内置中间件（prod 部署见 docs/deploy.md，只用 $(COMPOSE)）
COMPOSE_DEV := $(COMPOSE) -f deploy/docker-compose.dev.yml
BUNDLED := --profile bundled-mysql --profile bundled-redis

.PHONY: help up down migrate tailwind tailwind-watch test shell lint

help:  ## 列出可用命令
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: tailwind  ## 启动 dev（全内置 mysql+redis + 源码挂载；自动先编译 Tailwind）
	$(COMPOSE_DEV) $(BUNDLED) up -d

down:  ## 关停所有容器（保留 named volume）
	$(COMPOSE_DEV) $(BUNDLED) down

migrate:  ## 跑 Django migrations
	$(COMPOSE) exec web python manage.py migrate

tailwind: ## 一次性构建 Tailwind + DaisyUI 产物（自动 npm install）
	[ -d src/node_modules ] || (cd src && npm install)
	cd src && npm run build

tailwind-watch: ## 监听文件变化自动重构 Tailwind 产物（自动 npm install）
	[ -d src/node_modules ] || (cd src && npm install)
	cd src && npm run watch

test:  ## 跑 pytest（host，TEST_USE_SQLITE 模式；自动起 redis 容器供 /healthz 探活）
	@$(COMPOSE) --profile bundled-redis up -d redis
	cd src && TEST_USE_SQLITE=1 uv run pytest -v

shell:  ## 进 web 容器 Django shell
	$(COMPOSE) exec web python manage.py shell

lint:  ## 跑 ruff
	cd src && uv run ruff check .
