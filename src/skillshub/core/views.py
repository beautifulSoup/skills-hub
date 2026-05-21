"""Core views：/healthz + /index。"""
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
import redis
from django.conf import settings


def healthz(request):
    """同步探 DB + Redis 连通性。"""
    checks = {}

    # DB
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"fail: {exc}"

    # Redis
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"fail: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    return JsonResponse(
        {"status": "ok" if all_ok else "degraded", "checks": checks},
        status=200 if all_ok else 503,
    )


def index(request):
    """根路由：hero badge 含已发布数 + 最新发布 6 个 skill 预览。"""
    from skillshub.catalog.queries import list_skills
    from skillshub.submit.models import Skill

    latest_skills, _ = list_skills(q="", tags=[], sort="newest", page=1)
    published_count = Skill.objects.filter(latest_version__isnull=False).count()
    return render(request, "index.html", {
        "latest_skills": latest_skills[:6],
        "published_count": published_count,
    })
