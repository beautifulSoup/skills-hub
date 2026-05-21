"""
skills-hub Django settings（单文件 + django-environ）。

所有"会随环境变"的配置走 .env；本文件只读 env、给 fallback default。
按需求 D-T1-2 决策：不拆 base/dev/prod 三层文件。
"""
from pathlib import Path
import environ

# 用 PyMySQL 替代 mysqlclient（纯 Python，无 C 编译依赖；性能比 mysqlclient 略低但 MVP 够用）
import pymysql
pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # = <repo>/src/

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DB_PORT=(int, 3306),
    EXPOSE_DEMO=(bool, False),
    TOOLS_YAML_PATH=(str, ""),
    INITIAL_ADMIN_EMAILS=(list, []),
    EMAIL_DOMAIN_WHITELIST=(list, []),
)
# .env 在 deploy/.env（容器内由 docker-compose env_file 注入；host 跑 pytest 时本地读取）
environ.Env.read_env(BASE_DIR.parent / "deploy" / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
EXPOSE_DEMO = env("EXPOSE_DEMO")

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "skillshub.core",
    "skillshub.demo",
    "skillshub.notifications",
    "skillshub.tools",
    "skillshub.storage",
    "skillshub.accounts",
    "skillshub.submit",
    "skillshub.catalog",
    "skillshub.install",
]

from django.urls import reverse_lazy

UNFOLD = {
    "SITE_TITLE": "skills-hub 审核台",
    "SITE_HEADER": "skills-hub",
    "SITE_SUBHEADER": "企业私有 AI 工具仓库 · 审核台",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "COLORS": {
        "primary": {
            "50": "250 245 255",
            "100": "243 232 255",
            "200": "233 213 255",
            "300": "216 180 254",
            "400": "192 132 252",
            "500": "168 85 247",
            "600": "147 51 234",
            "700": "126 34 206",
            "800": "107 33 168",
            "900": "88 28 135",
            "950": "59 7 100",
        },
    },
    "SIDEBAR": {
        "show_search": False,
        "show_all_applications": False,
        "navigation": [
            {
                "items": [
                    {
                        "title": "主页",
                        "icon": "dashboard",
                        "link": reverse_lazy("admin:index"),
                    },
                    {
                        "title": "Skill 列表",
                        "icon": "extension",
                        "link": reverse_lazy("admin:submit_skill_changelist"),
                    },
                    {
                        "title": "Skill 审核",
                        "icon": "schedule",
                        "link": reverse_lazy("admin:submit_pendingskillversion_changelist"),
                    },
                    {
                        "title": "管理员管理",
                        "icon": "admin_panel_settings",
                        "link": reverse_lazy("admin:accounts_adminuser_changelist"),
                    },
                ],
            },
        ],
    },
}

MIDDLEWARE = [
    "skillshub.core.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise：DEBUG=False 下由 gunicorn 直接 serve 静态（K8s 无 nginx sidecar）
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "skillshub.core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "skillshub.core.wsgi.application"

if env.bool("TEST_USE_SQLITE", default=False):
    # 本地 pytest 默认用内存 SQLite，不依赖 MySQL 容器；
    # 本地 dev 用 runserver 看页面时，env DJANGO_DEV_SQLITE_PATH=/path/file.sqlite3
    # 切换到文件 SQLite，让数据跨进程持久（migrate / createsuperuser / runserver
    # 共用同一份 db）。
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env("DJANGO_DEV_SQLITE_PATH", default=":memory:"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT"),
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise 压缩存储（不带 manifest 哈希，避免引用缺失导致 500；prod 由 gunicorn serve）
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# === Storage (T3) ===
STORAGE_BACKEND = env("STORAGE_BACKEND", default="local")
STORAGE_LOCAL_ROOT = env("STORAGE_LOCAL_ROOT", default="/app/data/storage")
STORAGE_OSS_ACCESS_KEY_ID = env("STORAGE_OSS_ACCESS_KEY_ID", default="")
STORAGE_OSS_ACCESS_KEY_SECRET = env("STORAGE_OSS_ACCESS_KEY_SECRET", default="")
STORAGE_OSS_ENDPOINT = env("STORAGE_OSS_ENDPOINT", default="")
STORAGE_OSS_BUCKET = env("STORAGE_OSS_BUCKET", default="")
MEDIA_URL = "/media/"
MEDIA_ROOT = STORAGE_LOCAL_ROOT

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# === Celery ===
REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
if env.bool("TEST_USE_SQLITE", default=False):
    # 本地 pytest：用内存 cache 后端，不依赖 Redis 容器
    # 注意：Celery 5 的 Settings.result_backend property 会先查 os.environ，
    # 所以需要在此处同时覆写 os.environ，否则 .env 里的值会被优先读到。
    import os as _os
    _os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
    _os.environ["CELERY_BROKER_URL"] = "memory://"
    REDIS_URL = "redis://localhost:6379/0"   # Docker redis exposed on host
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_CACHE_BACKEND = "memory"
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    CELERY_TASK_STORE_EAGER_RESULT = True
else:
    CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/1")
    CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/2")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# === Email (T11) ===
# 按环境矩阵自动切 backend；caller 无需感知。
# FORCE_SMTP=True 可在 DEBUG=True 下强制走真 SMTP（本地联调真发信用），不影响生产。
if env.bool("TEST_USE_SQLITE", default=False):
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
elif DEBUG and not env.bool("FORCE_SMTP", default=False):
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("SMTP_HOST", default="")
    EMAIL_PORT = env.int("SMTP_PORT", default=587)
    EMAIL_HOST_USER = env("SMTP_USER", default="")
    EMAIL_HOST_PASSWORD = env("SMTP_PASSWORD", default="")
    # 465 = 隐式 SSL；587/其他 = STARTTLS。Django 中两者互斥。
    EMAIL_USE_SSL = EMAIL_PORT == 465
    EMAIL_USE_TLS = not EMAIL_USE_SSL
DEFAULT_FROM_EMAIL = env("SMTP_FROM", default="") or "noreply@skills-hub.local"
BASE_URL = env("BASE_URL", default="http://localhost:8000")

# === 反向代理 / Ingress（TLS 在入口终止，转发到容器是 http）===
# 让 Django 信任入口域名的跨源 POST（admin/登录），并据 X-Forwarded-Proto 识别 https
CSRF_TRUSTED_ORIGINS = [BASE_URL]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG and not env.bool("TEST_USE_SQLITE", default=False):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# === Tools (T4) ===
TOOLS_YAML_PATH = env("TOOLS_YAML_PATH") or str(BASE_DIR.parent / "config" / "tools.yaml")

# === Logging ===
from skillshub.core.logging_conf import build_logging_dict  # noqa: E402
LOGGING = build_logging_dict(debug=DEBUG)

# === Auth (T2) ===
INITIAL_ADMIN_EMAILS = env("INITIAL_ADMIN_EMAILS")
EMAIL_DOMAIN_WHITELIST = env("EMAIL_DOMAIN_WHITELIST")
LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/"

# === Session ===
SESSION_COOKIE_AGE = 30 * 24 * 3600  # 30 天
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
