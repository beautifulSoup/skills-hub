"""Install endpoints (T10 R-10):

- GET /install/<token>.sh  → POSIX 安装脚本
- GET /install/<token>.ps1 → PowerShell 安装脚本
- GET /install/<token>/zip → 302 redirect 到 storage URL
"""
from django.urls import path

from skillshub.install import views

urlpatterns = [
    path("<str:token>.sh", views.install_script_view, {"platform": "posix"}, name="install_script_sh"),
    path("<str:token>.ps1", views.install_script_view, {"platform": "windows"}, name="install_script_ps1"),
    path("<str:token>/zip", views.install_zip_view, name="install_zip"),
]
