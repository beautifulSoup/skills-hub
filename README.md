# skills-hub

企业私有 AI 工具仓库 —— 为团队提供一套结构化的方式来收集、审核与分发面向 Claude Code 等 AI 工具的 **skills / subagents**，让成员"按需下载、开箱即用"，把个人零散的 skill 沉淀为团队共享资产。

核心闭环：**成员提交 → 机器审查 + 人工审核 → 发布 → 团队浏览 / 搜索 / 一键安装**。

## 功能

- **提交**：上传 skill（zip，含 `SKILL.md` + 说明文档），支持多版本保留
- **审核**：机器审查（L1 结构校验 + L2 安全扫描，纯规则、无 LLM）→ 人工审核队列（Django Admin）+ 审计日志
- **浏览 / 搜索**：catalog 列表、关键字搜索、标签筛选、详情页
- **安装**：三种方式（CLI 脚本 / 向 AI 粘贴自然语言 / 手动下载 zip）× 三平台（Linux / macOS / Windows）
- **多工具目标**：配置驱动（`config/tools.yaml`），开箱支持 Claude Code、WorkBuddy，可自行扩展
- **认证**：企业邮箱白名单 + OTP 登录（无密码、无注册），member / admin 两档角色
- **可插拔基础设施**：MySQL / Redis 均可在「内置容器」与「外部实例」间切换；文件存储支持本地盘或阿里云 OSS
- **通知**：SMTP 邮件（OTP、审核结果）

技术栈：Django 5 · MySQL 8 · Celery + Redis · Tailwind CSS v4 + DaisyUI · Docker Compose。

## 快速开始（POC / 全内置，只需 Docker）

```bash
git clone <repo> skills-hub
cd skills-hub
cp deploy/.env.example deploy/.env        # 全内置形态的默认值即可跑通，按需改密钥/域名
docker compose -f deploy/docker-compose.yml \
  --profile bundled-mysql --profile bundled-redis up -d --build
curl localhost:8000/healthz               # → {"status":"ok","checks":{"db":"ok","redis":"ok"}}
```

镜像在构建阶段已编译好前端产物，**部署机只需 Docker，无需安装 Node / Python**。首次创建管理员、登录与完整验证流程见 [`docs/deploy.md`](docs/deploy.md)。

> 本地开发可用 `make up`（叠加源码挂载即时生效 + 自动编译 Tailwind，需本机 npm）。`make help` 查看全部命令。

## 部署形态：内置 / 外部中间件自由组合

MySQL 和 Redis 各自独立，都可在「内置容器」与「外部实例」之间切换：

| 中间件 | 用内置 | 用外部 |
|---|---|---|
| MySQL | 加 `--profile bundled-mysql` | `.env` 设 `DB_HOST` 等指向外部 RDS（不加该 profile） |
| Redis | 加 `--profile bundled-redis` | `.env` 设 `REDIS_URL` / `CELERY_*` 指向外部 Redis（不加该 profile） |

按 `deploy/.env.example` 各区块的「形态 A 外部 / 形态 B 内置」注释切换连接串即可。生产推荐 MySQL 用外部 RDS（数据有备份 / HA）；Redis 仅作 Celery 传输、不存持久数据，内置容器几乎零运维。

完整生产部署文档（`.env` 详解、healthcheck、上线 checklist、反向代理 / HTTPS、升级）见 [`docs/deploy.md`](docs/deploy.md)。

## 测试

```bash
make test     # host 上跑 pytest（TEST_USE_SQLITE 模式：内存 SQLite + 内存 Celery broker）
```

单元测试不依赖 MySQL / Redis 容器（仅 `/healthz` 探活需要一个 redis 容器，`make test` 会自动起）。本机需安装 [uv](https://docs.astral.sh/uv/)。

## License

[Apache-2.0](LICENSE) © 2026 Tango
