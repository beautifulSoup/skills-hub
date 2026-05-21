# syntax=docker/dockerfile:1.7
#
# Build context = repo root (set by docker-compose.yml's `build.context: ..`)
# 所有 COPY path 都相对 root；只 copy src/ 进 image，不带 docs/spec/openspec 等

# ============================================================
# Stage 1: frontend（node:20-alpine 构建 Tailwind + DaisyUI CSS）
# ============================================================
FROM node:20-alpine AS frontend

WORKDIR /frontend

COPY src/package.json src/package-lock.json ./
RUN npm install

COPY src/static/css/input.css static/css/input.css
COPY src/templates templates
COPY src/skillshub skillshub

RUN npx @tailwindcss/cli -i static/css/input.css -o static/css/output.css --minify

# ============================================================
# Stage 2: builder（uv 装依赖到 .venv）
# ============================================================
FROM python:3.12-slim AS builder

# uv 二进制
COPY --from=ghcr.io/astral-sh/uv:0.4 /uv /usr/local/bin/uv

WORKDIR /app

# 装依赖到 /opt/venv（**直接装到目标位置，避免后续 mv 导致 shebang 失效**）
# PyMySQL 是纯 Python，无需 apt 编译依赖
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
COPY src/pyproject.toml src/uv.lock ./
RUN uv sync --frozen --no-dev

# ============================================================
# Stage 3: runtime
# ============================================================
FROM python:3.12-slim AS runtime

# curl 给 compose web healthcheck 用（探 /healthz）；PyMySQL 是纯 Python 无需其它 apt 依赖
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从 builder 复制虚拟环境（builder 已装在 /opt/venv，shebang 路径正确）
# venv 不在 /app 下，dev 模式 compose mount `../src:/app` 不会 shadow
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 应用代码（只 copy src/ 进 image；dev 模式下会被 compose `../src:/app` mount 覆盖）
COPY src/ .

# 用 frontend stage 构建的 minified CSS 覆盖 git 中的版本（确保 prod 总是最新构建）
COPY --from=frontend /frontend/static/css/output.css /app/static/css/output.css

EXPOSE 8000

# 默认 entrypoint：dev runserver；compose 内可 override
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
