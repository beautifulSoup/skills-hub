"""Admin 自定义视图：审核详情页 + 单文件预览。

T8 R-7：admin 在 /admin/submit/skillversion/<id>/review/ 走完整审核流程。
权限：通过 SkillVersionAdmin.get_urls() 注册时套 admin_view 装饰器，
等价于 staff_member_required + login 跳转。
"""
import io
import logging
import os
import pathlib
import urllib.parse
import zipfile

from django.contrib import admin as django_admin
from django.contrib import messages
from django.contrib.admin.models import CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_GET, require_http_methods

from skillshub.catalog.markdown_render import render_readme


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _admin_context(request, extra: dict | None = None) -> dict:
    """合并 admin_site.each_context（含 has_permission / is_nav_sidebar_enabled /
    available_apps / current_app 等），让自定义 admin 视图也能渲染出
    Unfold 的完整 chrome（侧边栏、header 面包屑、modal 等）。
    """
    ctx = dict(django_admin.site.each_context(request))
    if extra:
        ctx.update(extra)
    return ctx


def _log_skill_change(request, skill, message: str) -> None:
    """写一条 LogEntry，让操作出现在 Skill admin 的"历史"页。"""
    LogEntry.objects.log_actions(
        user_id=request.user.pk,
        queryset=[skill],
        action_flag=CHANGE,
        change_message=message,
        single_object=True,
    )

from skillshub.storage.api import get_storage
from skillshub.submit.models import ReviewAction, Skill, SkillVersion
from skillshub.submit.services import (
    InvalidOperationError,
    InvalidStateError,
    approve_version,
    delist_skill,
    disable_version,
    enable_version,
    reject_version,
    relist_skill,
    request_changes_version,
    rollback_skill,
)

logger = logging.getLogger(__name__)

# 与 L1 后缀白名单一致（machine_review.l1 已定义）
PREVIEWABLE_SUFFIXES = {
    ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".txt", ".sh", ".toml",
}
PREVIEW_MAX_SIZE = 200 * 1024  # 200 KB

# 后缀 → highlight.js language class（marked.js 处理 .md，不在此表）
_HLJS_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".txt": "plaintext", ".sh": "bash", ".toml": "ini",
}


def _human_size(n: int) -> str:
    """字节 → 人类可读："1.2 KB" / "3.4 MB"。"""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _zip_entries(file_path: str) -> list[dict]:
    """读 zip namelist + size + previewable 标记。zip 读不到则返回 []。"""
    storage = get_storage()
    try:
        raw = storage.get(file_path)
    except FileNotFoundError:
        return []

    entries = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            suffix = pathlib.Path(info.filename).suffix.lower()
            entries.append({
                "path": info.filename,
                "size": info.file_size,
                "size_human": _human_size(info.file_size),
                "previewable": (
                    suffix in PREVIEWABLE_SUFFIXES
                    and info.file_size <= PREVIEW_MAX_SIZE
                ),
            })
    return entries


def _open_zip_or_400(version: SkillVersion) -> tuple[bytes, zipfile.ZipFile] | HttpResponse:
    """读 zip，返回 (raw_bytes, ZipFile) 或 HttpResponseBadRequest。"""
    storage = get_storage()
    try:
        raw = storage.get(version.file_path)
    except FileNotFoundError:
        return HttpResponseBadRequest("zip 文件不存在")
    return raw, zipfile.ZipFile(io.BytesIO(raw))


def _build_version_review_context(request, version: SkillVersion) -> dict:
    """构造 review / view 两个端点共享的 GET context（基础信息 + 文件清单 + 下载链接）。"""
    skill = version.skill
    return _admin_context(request, {
        "version": version,
        "skill": skill,
        "violations": version.violations or [],
        "readme_html": render_readme(version.readme or ""),
        "zip_entries": _zip_entries(version.file_path),
        "zip_download_url": reverse(
            "admin:submit_skillversion_zip_download", args=[version.pk]
        ),
        "file_download_base": reverse(
            "admin:submit_skillversion_file_download", args=[version.pk]
        ),
        "file_preview_base": reverse(
            "admin:submit_skillversion_file_preview", args=[version.pk]
        ),
        "opts": Skill._meta,
        "original": skill,
    })


@require_http_methods(["GET", "POST"])
def review_view(request, object_id: int):
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill", "submitted_by"),
        pk=object_id,
    )

    if request.method == "POST":
        action = request.POST.get("action", "")
        reason = request.POST.get("reason", "")
        try:
            if action == "approve":
                approve_version(version, actor=request.user, reason=reason)
                messages.success(request, f"已通过 v{version.version_no}。")
            elif action == "reject":
                reject_version(version, actor=request.user, reason=reason)
                messages.success(request, f"已拒绝 v{version.version_no}。")
            elif action == "request_changes":
                # 仅服务层保留，UI 已不暴露入口
                request_changes_version(version, actor=request.user, reason=reason)
                messages.success(request, f"已要求修改 v{version.version_no}。")
            else:
                return HttpResponseBadRequest("未知 action")
        except (InvalidStateError, ValueError) as e:
            logger.warning("review action failed for version=%s: %s", object_id, e)
            messages.error(request, str(e))
            return redirect(
                reverse("admin:submit_skillversion_review", args=[object_id])
            )
        # 跳回审核列表（PendingSkillVersion proxy — 侧边栏菜单同款）
        return redirect("admin:submit_pendingskillversion_changelist")

    # GET
    context = _build_version_review_context(request, version)
    context.update({
        "title": f"审核 {version.skill.name} v{version.version_no}",
        "breadcrumb_extra": [
            {
                "title": "审核",
                "link": reverse("admin:submit_pendingskillversion_changelist"),
            },
            {"title": f"v{version.version_no}"},
        ],
        "back_url": reverse("admin:submit_pendingskillversion_changelist"),
        "readonly": False,
    })
    return render(request, "admin/submit/skillversion/review.html", context)


@require_GET
def version_view(request, object_id: int):
    """只读版本详情页（从 SkillAdmin 版本子页「查看」按钮 / 版本号链接进入）。

    复用 review.html 布局；context.readonly=True 让模板隐藏审核结果表单。
    """
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill", "submitted_by"),
        pk=object_id,
    )
    context = _build_version_review_context(request, version)
    context.update({
        "title": f"查看 {version.skill.name} v{version.version_no}",
        "breadcrumb_extra": [
            {
                "title": "版本",
                "link": reverse(
                    "admin:submit_skill_versions", args=[version.skill.pk]
                ),
            },
            {"title": f"查看 v{version.version_no}"},
        ],
        "back_url": reverse(
            "admin:submit_skill_versions", args=[version.skill.pk]
        ),
        "readonly": True,
    })
    return render(request, "admin/submit/skillversion/review.html", context)


@require_GET
def file_view(request, object_id: int):
    """旧 htmx 内联预览端点 —— 保留给 version_detail.html 使用。"""
    version = get_object_or_404(SkillVersion, pk=object_id)
    path = request.GET.get("path", "")
    if not path:
        return HttpResponseBadRequest("缺 path 参数")

    suffix = pathlib.Path(path).suffix.lower()
    if suffix not in PREVIEWABLE_SUFFIXES:
        return HttpResponseBadRequest("文件后缀不在预览白名单")

    storage = get_storage()
    try:
        raw = storage.get(version.file_path)
    except FileNotFoundError:
        return HttpResponseBadRequest("zip 文件不存在")

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        if path not in zf.namelist():
            return HttpResponseBadRequest("path 不在 zip 内")
        info = zf.getinfo(path)
        if info.file_size > PREVIEW_MAX_SIZE:
            return HttpResponseBadRequest(
                f"文件超过预览上限 {PREVIEW_MAX_SIZE} B"
            )
        try:
            content = zf.read(path).decode("utf-8")
        except UnicodeDecodeError:
            return HttpResponseBadRequest("文件不是 UTF-8 文本")

    return HttpResponse(
        escape(content),
        content_type="text/html; charset=utf-8",
    )


def _content_disposition(filename: str) -> str:
    """RFC 5987 风格的 Content-Disposition，兼容中文文件名。"""
    quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename*=UTF-8''{quoted}"


@require_GET
def zip_download_view(request, object_id: int):
    """下载整包 zip（staff only，经 admin_view 装饰）。"""
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill"), pk=object_id
    )
    storage = get_storage()
    try:
        raw = storage.get(version.file_path)
    except FileNotFoundError:
        return HttpResponseBadRequest("zip 文件不存在")
    download_name = f"{version.skill.name}-v{version.version_no}.zip"
    resp = HttpResponse(raw, content_type="application/zip")
    resp["Content-Disposition"] = _content_disposition(download_name)
    return resp


@require_GET
def file_download_view(request, object_id: int):
    """下载 zip 内单个文件（任意后缀都允许，仅 staff）。"""
    version = get_object_or_404(SkillVersion, pk=object_id)
    path = request.GET.get("path", "")
    if not path:
        return HttpResponseBadRequest("缺 path 参数")

    storage = get_storage()
    try:
        raw = storage.get(version.file_path)
    except FileNotFoundError:
        return HttpResponseBadRequest("zip 文件不存在")

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        if path not in zf.namelist():
            return HttpResponseBadRequest("path 不在 zip 内")
        content = zf.read(path)

    resp = HttpResponse(content, content_type="application/octet-stream")
    resp["Content-Disposition"] = _content_disposition(os.path.basename(path))
    return resp


@require_GET
def file_preview_view(request, object_id: int):
    """独立预览页（新标签页打开）：
    - .md → 服务端 render_readme（已 bleach 清洗）
    - 其他白名单后缀 → highlight.js 客户端高亮
    """
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill"), pk=object_id
    )
    path = request.GET.get("path", "")
    if not path:
        return HttpResponseBadRequest("缺 path 参数")

    suffix = pathlib.Path(path).suffix.lower()
    if suffix not in PREVIEWABLE_SUFFIXES:
        return HttpResponseBadRequest("文件后缀不在预览白名单")

    storage = get_storage()
    try:
        raw = storage.get(version.file_path)
    except FileNotFoundError:
        return HttpResponseBadRequest("zip 文件不存在")

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        if path not in zf.namelist():
            return HttpResponseBadRequest("path 不在 zip 内")
        info = zf.getinfo(path)
        if info.file_size > PREVIEW_MAX_SIZE:
            return HttpResponseBadRequest(
                f"文件超过预览上限 {PREVIEW_MAX_SIZE} B"
            )
        try:
            text = zf.read(path).decode("utf-8")
        except UnicodeDecodeError:
            return HttpResponseBadRequest("文件不是 UTF-8 文本")

    ctx = {
        "version": version,
        "path": path,
        "size_human": _human_size(info.file_size),
        "download_url": (
            reverse(
                "admin:submit_skillversion_file_download", args=[object_id]
            )
            + f"?path={urllib.parse.quote(path, safe='')}"
        ),
    }
    if suffix == ".md":
        ctx["mode"] = "markdown"
        ctx["rendered_html"] = render_readme(text)
    else:
        ctx["mode"] = "code"
        ctx["language"] = _HLJS_LANG.get(suffix, "plaintext")
        ctx["raw"] = text
    return render(request, "admin/submit/skillversion/file_preview.html", ctx)


@require_http_methods(["GET", "POST"])
def listing_dialog_view(request, object_id: int):
    """Skill 详情页的上下线弹窗。

    GET → 返回 #dialog 片段（htmx 加载到 Unfold 的 #modal-content）。
    POST → 执行 delist/relist，成功后用 HX-Redirect 让浏览器跳回详情页。
    """
    skill = get_object_or_404(Skill, pk=object_id)
    op = "delist" if skill.is_listed else "relist"
    op_label = "下线" if op == "delist" else "上线"

    ctx = {
        "skill": skill,
        "op": op,
        "op_label": op_label,
        "error_message": None,
        "submitted_reason": "",
    }

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            ctx["error_message"] = "理由必填"
            ctx["submitted_reason"] = reason
            return render(
                request, "admin/submit/skill/listing_dialog.html", ctx
            )
        service_fn = delist_skill if op == "delist" else relist_skill
        try:
            service_fn(skill, actor=request.user, reason=reason)
        except (InvalidOperationError, ValueError) as e:
            ctx["error_message"] = str(e)
            ctx["submitted_reason"] = reason
            return render(
                request, "admin/submit/skill/listing_dialog.html", ctx
            )
        _log_skill_change(request, skill, f"{op_label} Skill：{reason}")
        messages.success(request, f"已{op_label} {skill.name}。")
        redirect_url = reverse(
            "admin:submit_skill_change", args=[object_id]
        )
        if _is_htmx(request):
            resp = HttpResponse(status=204)
            resp["HX-Redirect"] = redirect_url
            return resp
        return redirect(redirect_url)

    return render(request, "admin/submit/skill/listing_dialog.html", ctx)


_VERSION_OP_META = {
    "rollback": {
        "label": "回退到此版本",
        "desc": "把当前 latest 切到这个版本，原 latest 仍可在历史里查看。",
        "variant": "primary",
    },
    "disable": {
        "label": "下线版本",
        "desc": "下线后用户搜不到、下载会 404（其它版本不受影响）。",
        "variant": "danger",
    },
    "enable": {
        "label": "上线版本",
        "desc": "上线后用户可再次搜到 / 下载此版本。",
        "variant": "primary",
    },
}


@require_http_methods(["GET", "POST"])
def version_action_dialog_view(request, object_id: int, op: str):
    """版本列表页三类操作的统一弹窗：rollback / disable / enable。

    GET → 返回 #dialog 片段
    POST → 执行 service，HX-Redirect 跳回版本列表
    """
    if op not in _VERSION_OP_META:
        return HttpResponseBadRequest("op 不合法")
    meta = _VERSION_OP_META[op]
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill"), pk=object_id
    )
    skill = version.skill

    ctx = {
        "version": version,
        "skill": skill,
        "op": op,
        "op_label": meta["label"],
        "op_desc": meta["desc"],
        "op_variant": meta["variant"],
        "error_message": None,
        "submitted_reason": "",
    }

    def _render_dialog(extra=None):
        if extra:
            ctx.update(extra)
        return render(
            request, "admin/submit/skill/version_action_dialog.html", ctx
        )

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            return _render_dialog(
                {"error_message": "理由必填", "submitted_reason": reason}
            )
        try:
            if op == "rollback":
                rollback_skill(
                    skill, version, actor=request.user, reason=reason
                )
                ok_msg = f"已将 {skill.name} 切换到 v{version.version_no}。"
            elif op == "disable":
                disable_version(version, actor=request.user, reason=reason)
                ok_msg = f"已下线版本 v{version.version_no}。"
            else:  # enable
                enable_version(version, actor=request.user, reason=reason)
                ok_msg = f"已上线版本 v{version.version_no}。"
        except (InvalidOperationError, InvalidStateError, ValueError) as e:
            return _render_dialog(
                {"error_message": str(e), "submitted_reason": reason}
            )
        _log_skill_change(request, skill, f"{meta['label']} v{version.version_no}：{reason}")
        messages.success(request, ok_msg)
        redirect_url = reverse(
            "admin:submit_skill_versions", args=[skill.pk]
        )
        if _is_htmx(request):
            resp = HttpResponse(status=204)
            resp["HX-Redirect"] = redirect_url
            return resp
        return redirect(redirect_url)

    return _render_dialog()


@require_http_methods(["GET", "POST"])
def delete_dialog_view(request, object_id: int):
    """Skill 详情页的删除二次确认弹窗。

    GET → 返回 #dialog 片段（htmx 加载到 Unfold 的 #modal-content）。
    POST → 删除 Skill（先清 ReviewAction 解 PROTECT，再 cascade 删 SkillVersion）。
    成功后写一条 LogEntry（DELETION），HX-Redirect 跳回 Skill 列表。
    """
    skill = get_object_or_404(Skill, pk=object_id)
    versions_count = skill.versions.count()
    review_count = ReviewAction.objects.filter(version__skill=skill).count()

    if request.method == "POST":
        skill_pk = skill.pk
        skill_repr = str(skill)
        with transaction.atomic():
            ReviewAction.objects.filter(version__skill=skill).delete()
            skill.delete()
        LogEntry.objects.create(
            user_id=request.user.pk,
            content_type=ContentType.objects.get_for_model(Skill),
            object_id=str(skill_pk),
            object_repr=skill_repr[:200],
            action_flag=DELETION,
            change_message="",
        )
        messages.success(request, f"已删除 Skill {skill_repr}。")
        redirect_url = reverse("admin:submit_skill_changelist")
        if _is_htmx(request):
            resp = HttpResponse(status=204)
            resp["HX-Redirect"] = redirect_url
            return resp
        return redirect(redirect_url)

    return render(request, "admin/submit/skill/delete_dialog.html", {
        "skill": skill,
        "versions_count": versions_count,
        "review_count": review_count,
    })


@require_http_methods(["GET", "POST"])
def bulk_listing_view(request):
    """上下线统一入口（单条 N=1 与批量 N≥2 同一路径）。

    GET ?op=delist&ids=1,2,3 → 渲染 reason 表单
    POST ?op=delist&ids=1,2,3 + form data reason → 循环调 service，汇总 messages
    """
    op = request.GET.get("op", "")
    if op not in {"delist", "relist"}:
        return HttpResponseBadRequest("op 必须为 delist 或 relist")

    ids_raw = request.GET.get("ids", "")
    try:
        ids = [int(s) for s in ids_raw.split(",") if s]
    except ValueError:
        return HttpResponseBadRequest("ids 解析失败")
    if not ids:
        return HttpResponseBadRequest("ids 为空")

    skills = list(Skill.objects.filter(pk__in=ids).order_by("pk"))
    op_label = "下线" if op == "delist" else "上线"

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            return render(
                request,
                "admin/submit/skill/bulk_listing_confirm.html",
                {
                    "op": op,
                    "op_label": op_label,
                    "skills": skills,
                    "error_message": "reason 必填",
                    "submitted_reason": "",
                },
            )

        service_fn = delist_skill if op == "delist" else relist_skill
        success_count = 0
        skip_count = 0
        for s in skills:
            try:
                service_fn(s, actor=request.user, reason=reason)
            except (InvalidOperationError, ValueError) as e:
                logger.info("bulk %s skip skill=%s reason=%s", op, s.pk, e)
                skip_count += 1
                continue
            _log_skill_change(request, s, f"{op_label} Skill：{reason}")
            success_count += 1
        if success_count:
            if skip_count:
                msg = (
                    f"成功{op_label} {success_count} 个，"
                    f"跳过 {skip_count} 个（已{op_label}）"
                )
            else:
                msg = f"成功{op_label} {success_count} 个 skill"
            messages.success(request, msg)
        else:
            messages.warning(request, f"全部跳过（{skip_count} 个），未发生变更")
        return redirect("admin:submit_skill_changelist")

    return render(
        request,
        "admin/submit/skill/bulk_listing_confirm.html",
        {
            "op": op,
            "op_label": op_label,
            "skills": skills,
            "error_message": None,
            "submitted_reason": "",
        },
    )


@require_GET
def versions_view(request, object_id: int):
    """列出指定 skill 的全部 SkillVersion，按 version_no 倒序。

    每个 status=published 且非当前 latest_version 的版本旁有「设为当前版本」入口
    （跳到 rollback_view）。
    """
    skill = get_object_or_404(Skill, pk=object_id)
    versions = skill.versions.select_related("submitted_by").order_by("-version_no")
    latest_id = skill.latest_version_id

    rows = []
    for v in versions:
        is_published = v.status == SkillVersion.STATUS_PUBLISHED
        rows.append({
            "obj": v,
            "is_current": v.id == latest_id,
            "can_rollback": is_published and v.id != latest_id,
            # 下线/上线按钮只对已 published 的版本暴露 —— 未通过审核的版本
            # 还在 pending / rejected / changes_requested 等中间态，没意义。
            "show_listing_toggle": is_published,
            "is_available": v.is_available,
        })

    return render(
        request,
        "admin/submit/skill/versions.html",
        _admin_context(request, {
            "skill": skill,
            "rows": rows,
            "opts": Skill._meta,
            "original": skill,
            "title": f"{skill.name} 版本清单",
            "breadcrumb_extra": [{"title": "版本"}],
            "back_url": reverse(
                "admin:submit_skill_change", args=[skill.pk]
            ),
        }),
    )


@require_http_methods(["GET", "POST"])
def rollback_view(request, object_id: int):
    """把 skill.latest_version 设为指定 target_version。

    GET ?target=<v_id> → 渲染 reason 表单
    POST ?target=<v_id> + form data reason → 调 rollback_skill
    """
    skill = get_object_or_404(
        Skill.objects.select_related("latest_version"),
        pk=object_id,
    )
    target_id_raw = request.GET.get("target", "")
    try:
        target_id = int(target_id_raw)
    except ValueError:
        return HttpResponseBadRequest("target 参数无效")
    target = get_object_or_404(SkillVersion, pk=target_id)

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        try:
            rollback_skill(skill, target, actor=request.user, reason=reason)
        except ValueError as e:
            return render(
                request,
                "admin/submit/skill/rollback_confirm.html",
                {
                    "skill": skill, "target": target,
                    "error_message": str(e),
                    "submitted_reason": reason,
                },
            )
        except (InvalidStateError, InvalidOperationError) as e:
            messages.error(request, str(e))
            return redirect(
                reverse("admin:submit_skill_versions", args=[object_id])
            )
        messages.success(
            request, f"已将 {skill.name} 回退到 v{target.version_no}。"
        )
        return redirect(
            reverse("admin:submit_skill_versions", args=[object_id])
        )

    return render(
        request,
        "admin/submit/skill/rollback_confirm.html",
        {
            "skill": skill, "target": target,
            "error_message": None,
            "submitted_reason": "",
        },
    )


@require_http_methods(["POST"])
def disable_version_view(request, object_id: int):
    """下线单个版本（POST only）。

    POST body: reason
    重定向回 versions 列表 + messages.success/error
    """
    version = get_object_or_404(SkillVersion, pk=object_id)
    skill_id = version.skill_id
    reason = request.POST.get("reason", "").strip()
    try:
        disable_version(version, actor=request.user, reason=reason)
    except ValueError as e:
        messages.error(request, f"下线版本失败：{e}")
    except InvalidOperationError as e:
        messages.error(request, str(e))
    else:
        messages.success(
            request, f"已下线版本 v{version.version_no}。"
        )
    return redirect(
        reverse("admin:submit_skill_versions", args=[skill_id])
    )


@require_http_methods(["POST"])
def enable_version_view(request, object_id: int):
    """上线单个版本（POST only）。"""
    version = get_object_or_404(SkillVersion, pk=object_id)
    skill_id = version.skill_id
    reason = request.POST.get("reason", "").strip()
    try:
        enable_version(version, actor=request.user, reason=reason)
    except ValueError as e:
        messages.error(request, f"上线版本失败：{e}")
    except InvalidOperationError as e:
        messages.error(request, str(e))
    else:
        messages.success(
            request, f"已上线版本 v{version.version_no}。"
        )
    return redirect(
        reverse("admin:submit_skill_versions", args=[skill_id])
    )


@require_GET
def version_detail_view(request, object_id: int):
    """SkillVersion 详情页：全字段中文展示 + zip 文件浏览。

    与 T8 的 review_view 不同：review_view 是审核工作台（pending_review 状态 +
    三按钮），此 view 是只读详情（任何 status 版本都可看）。
    """
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill", "submitted_by"),
        pk=object_id,
    )
    return render(
        request,
        "admin/submit/skill/version_detail.html",
        _admin_context(request, {
            "version": version,
            "zip_entries": _zip_entries(version.file_path),
            "file_url_base": reverse(
                "admin:submit_skillversion_file", args=[object_id]
            ),
            "opts": Skill._meta,
            "original": version.skill,
            "title": f"{version.skill.name} v{version.version_no}",
            "breadcrumb_extra": [
                {
                    "title": "版本",
                    "link": reverse(
                        "admin:submit_skill_versions",
                        args=[version.skill_id],
                    ),
                },
                {"title": f"v{version.version_no}"},
            ],
            "back_url": reverse(
                "admin:submit_skill_versions", args=[version.skill_id]
            ),
        }),
    )
