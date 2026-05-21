"""Submit app URL patterns — /submit/"""
from django.urls import path

from skillshub.submit import views

urlpatterns = [
    path("", views.submit_view, name="submit"),
]
