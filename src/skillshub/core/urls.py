"""顶层 URL 路由。"""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from skillshub.core import views
from skillshub.accounts.views import logout_view

urlpatterns = [
    path("", views.index, name="index"),
    path("healthz", views.healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("login/", include("skillshub.accounts.urls")),
    path("logout/", logout_view, name="logout"),
    path("submit/", include("skillshub.submit.urls")),
    path("skills/", include("skillshub.submit.cancel_urls")),
    path("catalog/", include("skillshub.catalog.urls")),
    path("install/", include("skillshub.install.urls")),
]

if settings.EXPOSE_DEMO:
    urlpatterns.append(path("demo/", include("skillshub.demo.urls")))

# Dev: Django serves /media/ + /static/ directly (gunicorn doesn't, unlike runserver); prod: nginx handles both.
# staticfiles_urlpatterns 走 finders，覆盖项目 static + app 打包静态（admin / unfold），
# 比 static(document_root=...) 只服务单目录更全。
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += staticfiles_urlpatterns()
