"""核心 admin 配置：隐藏 Group（审核员不需要），保留 User（superuser 可见）。"""
from django.contrib import admin
from django.contrib.auth.models import Group

admin.site.unregister(Group)
