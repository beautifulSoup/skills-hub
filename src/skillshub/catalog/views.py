"""Catalog views: 列表 + 详情。"""
import json

from django.contrib.auth.decorators import login_required
from django.db.models import OuterRef, Subquery
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from skillshub.catalog.markdown_render import render_readme
from skillshub.catalog.queries import (
    DEFAULT_SORT,
    SORT_OPTIONS,
    list_skills,
)
from skillshub.install.ua import guess_os
from skillshub.submit.history import build_skill_events
from skillshub.submit.models import Skill, SkillVersion
from skillshub.tools.registry import list_supported, translate_path


def list_view(request):
    """GET /catalog/ — 列表页。

    Query params:
        q: 搜索关键词
        tags: 多选 tag (?tags=ai&tags=python)
        sort: newest / updated / installs (默认 installs)
        page: 1-based 页号 (默认 1)

    HTMX header (HX-Request: true) 时返回 partial (_load_more.html)，
    否则全页 (list.html)。
    """
    q = request.GET.get("q", "").strip()
    tags = request.GET.getlist("tags")
    sort = request.GET.get("sort", DEFAULT_SORT)
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT

    try:
        page = max(1, int(request.GET.get("page", "1")))
    except ValueError:
        page = 1

    skills, has_next = list_skills(q=q, tags=tags, sort=sort, page=page)

    context = {
        "skills": skills,
        "has_next": has_next,
        "next_page": page + 1,
        "q": q,
        "tags": tags,
        "sort": sort,
        "sort_options": SORT_OPTIONS.keys(),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "catalog/_load_more.html", context)
    return render(request, "catalog/list.html", context)


@login_required
def my_skills_view(request):
    """GET /catalog/mine/ — 当前用户创建的所有 skill（任何状态）。

    Skill.created_by 是第一作者；后续他人提交版本不改变 created_by 归属。
    用 Subquery 把最近一次 SkillVersion 的 status / version_no 取出来，便于
    模板渲染"已发布 / 待审 / 已拒绝"等状态徽章。
    """
    recent = SkillVersion.objects.filter(skill=OuterRef("pk")).order_by("-submitted_at")
    skills = (
        Skill.objects.filter(created_by=request.user)
        .select_related("latest_version")
        .annotate(
            recent_status=Subquery(recent.values("status")[:1]),
            recent_version_no=Subquery(recent.values("version_no")[:1]),
        )
        .order_by("-created_at")
    )
    return render(request, "catalog/my.html", {"skills": skills})


def detail_view(request, name):
    """GET /catalog/<name>/ — 详情页。

    默认渲染 skill.latest_version；?v=<n> 指定历史版本。

    owner override：作者本人可看自己尚未 published 的版本（pending_machine /
    pending_review / changes_requested）+ 页面显示状态 banner。非 owner 仅可见
    published 版本（latest 或 ?v=<n> 指定的）。
    """
    skill = get_object_or_404(
        Skill.objects.select_related("latest_version__submitted_by", "created_by"),
        name=name,
    )

    is_owner = request.user.is_authenticated and skill.created_by_id == request.user.id

    is_staff_user = request.user.is_authenticated and request.user.is_staff

    if not skill.is_listed:
        if not (is_owner or is_staff_user):
            raise Http404("skill 未公开")

    v_param = request.GET.get("v")
    if v_param:
        try:
            v_no = int(v_param)
        except ValueError:
            raise Http404("invalid version")
        # owner: 可看任意 status；非 owner: 仅 published
        qs = SkillVersion.objects.select_related("submitted_by")
        if not is_owner:
            qs = qs.filter(status=SkillVersion.STATUS_PUBLISHED)
        version = get_object_or_404(qs, skill=skill, version_no=v_no)
        # is_available 闸门：仅 owner / staff 可看下线版本
        if not version.is_available and not (is_owner or is_staff_user):
            raise Http404("version unavailable")
    elif skill.latest_version_id:
        version = skill.latest_version
        # is_available 闸门：latest_version 下线时，仅 owner / staff 可看
        if not version.is_available and not (is_owner or is_staff_user):
            raise Http404("version unavailable")
    elif is_owner:
        # 作者无 published 版本时，回落到最新 non-rejected/non-cancelled 版本
        version = (
            SkillVersion.objects.select_related("submitted_by")
            .filter(skill=skill)
            .exclude(status__in=[
                SkillVersion.STATUS_REJECTED,
                SkillVersion.STATUS_CANCELLED,
            ])
            .order_by("-submitted_at")
            .first()
        )
        if version is None:
            raise Http404("no viewable version")
    else:
        # 非 owner + 无 published：跟旧行为一致 404
        raise Http404("not published")

    # T10: install-block 上下文
    default_os = guess_os(request.META.get("HTTP_USER_AGENT", ""))
    tools_supporting_skill = list_supported("skill")
    default_tool = tools_supporting_skill[0]["id"] if tools_supporting_skill else "claude-code"

    paths: dict[str, dict[str, str]] = {}
    for t in tools_supporting_skill:
        paths[t["id"]] = {}
        for os_name in ("linux", "macos", "windows"):
            try:
                paths[t["id"]][os_name] = translate_path(
                    t["id"], "skill", os_name, skill.name
                )
            except (KeyError, ValueError):
                paths[t["id"]][os_name] = ""

    context = {
        "skill": skill,
        "version": version,
        "readme_html": render_readme(version.readme),
        "default_os": default_os,
        "default_tool": default_tool,
        "tools_json": json.dumps(tools_supporting_skill),
        "paths_json": json.dumps(paths),
        "origin_url": request.build_absolute_uri("/").rstrip("/"),
    }
    return render(request, "catalog/detail.html", context)


@login_required
def mine_detail_view(request, name):
    """GET /catalog/mine/<name>/ — owner-only skill 详情。

    与公开 detail_view 的差异：
      - 必须是 skill.created_by 才能访问，否则 404（不泄露存在性）
      - 默认渲染「最新一版」（不限 published），覆盖待审 / 已拒绝 / 已取消等
      - ?v=<n> 切换任意状态的历史版本
      - 渲染提交 / 审核历史时间线（build_skill_events，不含 admin 后台日志）
      - 顶部含「重新提交此 Skill」入口，跳 /submit/?skill=<name>
    """
    skill = get_object_or_404(
        Skill.objects.select_related("latest_version__submitted_by", "created_by"),
        name=name,
    )
    if not (request.user.is_authenticated and skill.created_by_id == request.user.id):
        raise Http404("非作者本人，看不到 owner 视图")

    versions_qs = (
        SkillVersion.objects.select_related("submitted_by")
        .filter(skill=skill)
        .order_by("-submitted_at")
    )

    v_param = request.GET.get("v")
    if v_param:
        try:
            v_no = int(v_param)
        except ValueError:
            raise Http404("invalid version")
        version = get_object_or_404(versions_qs, version_no=v_no)
    else:
        version = versions_qs.first()
        if version is None:
            raise Http404("no version submitted yet")

    # install-block 上下文（仅 published 版本会用到，但 context 始终注入便于模板 if）
    default_os = guess_os(request.META.get("HTTP_USER_AGENT", ""))
    tools_supporting_skill = list_supported("skill")
    default_tool = tools_supporting_skill[0]["id"] if tools_supporting_skill else "claude-code"
    paths: dict[str, dict[str, str]] = {}
    for t in tools_supporting_skill:
        paths[t["id"]] = {}
        for os_name in ("linux", "macos", "windows"):
            try:
                paths[t["id"]][os_name] = translate_path(
                    t["id"], "skill", os_name, skill.name,
                )
            except (KeyError, ValueError):
                paths[t["id"]][os_name] = ""

    context = {
        "skill": skill,
        "version": version,
        "readme_html": render_readme(version.readme or ""),
        "all_versions": list(versions_qs),
        "owner_events": build_skill_events(skill, include_admin_log=False),
        "resubmit_url": f"/submit/?skill={skill.name}",
        "default_os": default_os,
        "default_tool": default_tool,
        "tools_json": json.dumps(tools_supporting_skill),
        "paths_json": json.dumps(paths),
        "origin_url": request.build_absolute_uri("/").rstrip("/"),
    }
    return render(request, "catalog/mine_detail.html", context)
