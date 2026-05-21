# skills-hub 部署指南

本文档从 0 到部署完整教学，按顺序读完即可把 skills-hub 跑起来。

## 0. 前置条件

- Docker 24+ & Docker Compose v2.20+
- Git
- 一个企业邮箱后缀（如 `example.com`），用于白名单
- 一个 SMTP 中继（OTP 邮件 / 审核结果邮件用）

可选（按部署形态）：

- 云 RDS MySQL 8.x（推荐生产形态；不用则跑内置 mysql 容器）
- 外部 Redis（已有 Redis 集群时可接入；不用则跑内置 redis 容器）
- 阿里云 OSS bucket + ak/sk（生产存储推荐；本地盘也行）

> 部署只依赖 Docker —— 前端产物（Tailwind CSS）已在镜像构建阶段编译进镜像，**部署机无需安装 Node / Python**。

## 1. 克隆代码

```bash
git clone https://github.com/<your-org>/skills-hub.git
cd skills-hub
```

## 2. 选部署形态

MySQL 与 Redis 各自独立，都能在「内置容器」与「外部实例」之间切换，自由组合：

| 中间件 | 内置（加对应 profile） | 外部（不加 profile，.env 指向外部） |
|---|---|---|
| **MySQL** | `--profile bundled-mysql`，compose 内置 `mysql:8.4`，数据在 docker volume | `.env` 设 `DB_HOST` 等指向云 RDS / 自建 MySQL，备份 / HA 由 RDS 接管 |
| **Redis** | `--profile bundled-redis`，compose 内置 `redis:7-alpine` | `.env` 设 `REDIS_URL` / `CELERY_*` 指向外部 Redis |

- **新手 / 试用 / 小团队 (<100 用户)**：两者都用内置（加上两个 profile），一行起来。
- **生产推荐**：MySQL 用外部 RDS（数据有备份 / HA）。Redis 仅作 Celery 的 broker + result backend、不存持久数据，内置容器几乎零运维；除非已有 Redis 集群，否则保持内置即可。

> Redis 用途说明：本项目 Redis 只承载异步任务（机器审查、发邮件），无缓存、无 session（session 走 DB）。它挂了只影响在途异步任务（可重跑），不丢业务数据。

## 3. 配置 .env

```bash
cp deploy/.env.example deploy/.env
```

打开 `deploy/.env`，按形态填写：

### 3.1 bundled-mysql 形态

`.env.example` 默认未注释段就是 bundled-mysql 配置：

```dotenv
DB_HOST=mysql               # compose 内部服务名
DB_PORT=3306
DB_NAME=skillshub
DB_USER=skillshub
DB_PASSWORD=<改成强密码>
DB_ROOT_PASSWORD=<改成另一个强密码>
```

### 3.2 external-rds 形态

注释 bundled-mysql 段，取消注释 external-rds 段：

```dotenv
DB_HOST=your-rds-endpoint.aliyuncs.com
DB_PORT=3306
DB_NAME=skillshub
DB_USER=skillshub
DB_PASSWORD=<RDS 账号密码>
```

### 3.3 Redis（内置 / 外部）

`.env.example` 默认未注释段是**内置 Redis**（启动时加 `--profile bundled-redis`）：

```dotenv
REDIS_URL=redis://redis:6379/0          # redis 为 compose 内部服务名
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
```

用**外部 Redis** 时注释上面三行、取消注释「形态 A」段并指向外部地址（启动**不**加 `--profile bundled-redis`）：

```dotenv
REDIS_URL=redis://your-redis-host:6379/0
CELERY_BROKER_URL=redis://your-redis-host:6379/1
CELERY_RESULT_BACKEND=redis://your-redis-host:6379/2
```

### 3.4 其他必填字段

不管选哪个形态都要填：

```dotenv
DJANGO_SECRET_KEY=<生成方式见下>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your-domain.example.com
BASE_URL=https://your-domain.example.com

# SMTP（OTP 邮件 + 审核结果邮件）
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=<SMTP 凭证>
SMTP_FROM=noreply@example.com

# 邮箱白名单（控制谁能登录）
EMAIL_DOMAIN_WHITELIST=example.com,subsidiary.example.com

# 初始管理员（migrate 时自动同步为 is_staff=True）
INITIAL_ADMIN_EMAILS=admin1@example.com,admin2@example.com

# 存储后端
STORAGE_BACKEND=local              # 或 aliyun_oss
STORAGE_LOCAL_ROOT=/app/data/storage
```

生成 `DJANGO_SECRET_KEY`：

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 4. 起容器

按所选形态加对应 profile（首次需 `--build` 本地构建镜像，仅依赖 Docker）：

```bash
# 全内置（内置 mysql + 内置 redis）
docker compose -f deploy/docker-compose.yml \
  --profile bundled-mysql --profile bundled-redis up -d --build

# 全外部（.env 已指向外部 RDS + 外部 Redis）
docker compose -f deploy/docker-compose.yml up -d --build

# 混合举例：内置 mysql + 外部 redis（只加一个 profile）
docker compose -f deploy/docker-compose.yml --profile bundled-mysql up -d --build
```

> **prod 用上面的 `-f deploy/docker-compose.yml`**（镜像自带前端产物，部署机无需 Node）。
> 本地开发用 `make up`：它会叠加 `deploy/docker-compose.dev.yml` 挂载源码即时生效（默认全内置），因此需要本机 npm 编译 Tailwind（`make up` 已自动 `make tailwind`）—— **不要在生产用 `make up`**。

等 60 秒左右（mysql 冷启动 ~20s，web healthcheck 等 mysql healthy 再起）。

观察日志：

```bash
docker compose -f deploy/docker-compose.yml logs -f web
```

## 5. 验证 /healthz

```bash
curl http://localhost:8000/healthz
```

期望返回 200 + JSON：

```json
{"db": "ok", "redis": "ok"}
```

如果不通，跳到 [9. 常见排错](#9-常见排错)。

## 6. 创建初始 admin

`INITIAL_ADMIN_EMAILS` 在 migrate 时已自动同步为 Django staff 用户。可登录 admin：

1. 浏览器访问 `https://your-domain.example.com/login/`
2. 输入 `INITIAL_ADMIN_EMAILS` 里列的邮箱
3. SMTP 收 OTP 验证码
4. 输入验证码登录
5. 进 `/admin/` 看审核台

如需把 admin 提升为 superuser（看 Django auth 用户管理 / 加更多 admin）：

```bash
docker compose -f deploy/docker-compose.yml exec web python manage.py shell -c "
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(email='admin1@example.com')
u.is_superuser = True; u.save()
"
```

## 7. 浏览器验证全流程

1. `https://your-domain.example.com/` — 首页
2. `https://your-domain.example.com/catalog/` — Skill 列表（空状态：暂无已发布）
3. 登录 admin → `/submit/` 提交一个 demo zip skill
4. `/admin/submit/skillversion/` 看到「待审队列 FIFO」横幅
5. 点 review → approve → 状态变 published
6. 回 `/catalog/` → 看到 demo skill 卡片
7. 点详情 → hero 下方有「📦 安装」区块
8. 复制 CLI 命令 → 终端跑 → SKILL.md 装到 `~/.claude/skills/<name>/`

完成上面 8 步即闭环可用。

## 8. 上线 checklist

生产部署前逐条勾选：

- [ ] `DJANGO_SECRET_KEY` 用 `get_random_secret_key()` 生成，**不能**留 .env.example 默认值
- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_ALLOWED_HOSTS` 填实际生产域名
- [ ] `BASE_URL=https://...` 填实际域名（邮件中链接用）
- [ ] DB 用外部 RDS（生产强烈建议）；bundled-mysql 仅 POC / 小团队
- [ ] `STORAGE_BACKEND=aliyun_oss` + `STORAGE_OSS_*` 全配齐（生产推荐 OSS）
- [ ] `SMTP_*` 全配 + 测试发件成功（OTP / 审核邮件依赖）
- [ ] `EMAIL_DOMAIN_WHITELIST` 设公司邮箱后缀，**禁止**留空（留空 = 任何邮箱都能登）
- [ ] `INITIAL_ADMIN_EMAILS` 填实际管理员邮箱
- [ ] 反向代理（nginx / Caddy / Traefik）+ HTTPS（Let's Encrypt / 企业 CA）
- [ ] DB 备份策略（RDS 自动快照 / 自建定时 mysqldump）
- [ ] 监控 `/healthz` + 日志收集（prometheus / loki / 企业内部监控）

## 9. 常见排错

### 9.1 web healthcheck 一直 unhealthy

```bash
docker compose logs web | tail -50
```

最常见原因：
- DB 连接失败 → 检查 `DB_HOST` / `DB_PORT` / 网络（bundled 形态 `DB_HOST=mysql`，external 形态填 RDS endpoint）
- migrate 没跑 → web 容器启动会自动 migrate，看 logs 是否有 `Operations to perform: Apply all migrations` + `OK`
- gunicorn worker 全 crash → logs 顶部找 traceback；常见是 secret key 没设 / settings.py 加载失败

### 9.2 mysql healthcheck 一直 unhealthy（bundled 形态）

```bash
docker compose logs mysql | tail -30
```

常见原因：
- `MYSQL_ROOT_PASSWORD` 没设（healthcheck 用 root 探活）
- 冷启动 ~20 秒，给 `start_period: 30s` buffer 已够；若超 60s 仍 unhealthy 检查 mysql 容器 cpu / mem 限制

### 9.3 SMTP 不通 / OTP 邮件收不到

```bash
docker compose exec web python manage.py shell -c "
from django.core.mail import send_mail
send_mail('test', 'body', 'noreply@example.com', ['you@example.com'])
"
```

常见原因：
- 内网 SMTP 中继不允许容器 IP 发件 → 加白名单
- `SMTP_USER` / `SMTP_PASSWORD` 错 → 服务器返回 535 auth failed
- 端口 587 被防火墙挡 → 联系运维

### 9.4 OSS 上传失败 / 403 权限

```bash
docker compose exec web python manage.py shell -c "
from skillshub.storage.api import get_storage
s = get_storage()
print(s.url('test/path'))
"
```

常见原因：
- ak/sk 错 / 过期
- bucket 名拼错（注意 region 前缀，如 `oss-cn-beijing` vs `oss-cn-shanghai`）
- bucket policy 没开 PUT / GET 权限给 ak 对应 RAM 用户

### 9.5 storage 本地盘权限 denied

```bash
docker compose exec web ls -la /app/data/storage
```

容器内 `/app/data/storage` 应该可写。

常见原因：
- host 目录权限 root only → `chmod 777 data/storage` 或 `chown 1000:1000`（Django runtime UID）
- SELinux 限制（CentOS / RHEL）→ `:Z` mount flag 或 `setenforce 0` 调试

### 9.6 启动慢 / depends_on 等不到 healthy

bundled-mysql 冷启动 ~20s，web 等 mysql healthy。如果 `docker compose up` 后超过 60s 仍 web 没起：

```bash
docker compose ps
```

看每个服务 STATUS 列。如果 mysql 还是 `(starting)`：mysql 真启动慢，等等就好。如果 mysql `(unhealthy)`：跳 9.2 看 mysql logs。

## 10. 反向代理 / HTTPS（提示）

生产强烈建议在 web 容器前加反向代理：

- **nginx** + Let's Encrypt（最常见）
- **Caddy**（自动 HTTPS，零配置）
- **Traefik**（适合 docker 多服务）

参考各社区配置；本文档不一一展开（自托管用户生态各异）。

---

## 附：升级 skills-hub

```bash
cd skills-hub
git pull
# 用与首次启动相同的 profile 组合（此处示例全内置）
docker compose -f deploy/docker-compose.yml \
  --profile bundled-mysql --profile bundled-redis up -d --build
```

web 容器启动会自动跑 migrate。

---

文档反馈 / bug → GitHub Issues。
