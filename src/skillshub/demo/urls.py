"""Demo app URL 路由。父级 (core/urls.py) 用 `path("demo/", include(...))` 挂载。"""
from django.urls import path
from skillshub.demo import views

urlpatterns = [
    path("", views.enqueue_add, name="demo_enqueue"),         # /demo/
    path("<str:task_id>", views.get_result, name="demo_result"),  # /demo/<task_id>
]
