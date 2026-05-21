"""Cancel URL patterns — /skills/<skill_id>/versions/<version_id>/cancel"""
from django.urls import path

from skillshub.submit import views

urlpatterns = [
    path(
        "<int:skill_id>/versions/<int:version_id>/cancel",
        views.cancel_version,
        name="cancel_version",
    ),
]
