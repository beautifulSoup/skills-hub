"""Catalog app URL patterns — /catalog/"""
from django.urls import path

from skillshub.catalog import views

urlpatterns = [
    path("", views.list_view, name="catalog_list"),
    path("mine/", views.my_skills_view, name="my_skills"),
    path("mine/<slug:name>/", views.mine_detail_view, name="my_skill_detail"),
    path("<slug:name>/", views.detail_view, name="catalog_detail"),
]
