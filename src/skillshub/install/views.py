"""Install 视图 (T10): 渲染安装脚本 + 重定向 manual zip."""
import logging

from django.conf import settings
from django.db.models import F
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse

from skillshub.storage.api import get_storage
from skillshub.submit.models import Skill, SkillVersion
from skillshub.tools.registry import translate_path

logger = logging.getLogger(__name__)

VALID_OS = {"linux", "macos", "windows"}
DEFAULT_TOOL = "claude-code"
PLATFORM_DEFAULT_OS = {"posix": "linux", "windows": "windows"}
PLATFORM_TEMPLATE = {
    "posix": "install/script_posix.sh.j2",
    "windows": "install/script_windows.ps1.j2",
}
PLATFORM_CONTENT_TYPE = {
    "posix": "text/x-shellscript; charset=utf-8",
    "windows": "text/plain; charset=utf-8",
}


def _increment_install_count(skill_id: int) -> None:
    """F() atomic +1，异常吞 (log error) 不阻塞响应。"""
    try:
        Skill.objects.filter(id=skill_id).update(install_count=F("install_count") + 1)
    except Exception:
        logger.exception("failed to increment install_count for skill_id=%s", skill_id)


def _expand_target_path(template: str, platform: str) -> str:
    """tools.translate_path 的路径里 ~ / %USERPROFILE% 展开为 shell 变量。"""
    if platform == "posix":
        return template.replace("~", "$HOME")
    return template.replace("%USERPROFILE%", "$env:USERPROFILE")


def install_script_view(request, token, platform):
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill"),
        download_token=token,
        status=SkillVersion.STATUS_PUBLISHED,
        skill__is_listed=True,
        is_available=True,
    )

    tool_id = request.GET.get("tool", DEFAULT_TOOL)
    os = request.GET.get("os", PLATFORM_DEFAULT_OS[platform])

    if os not in VALID_OS:
        raise Http404(f"invalid os: {os}")

    if platform == "posix" and os == "windows":
        raise Http404("posix endpoint does not allow os=windows")
    if platform == "windows" and os != "windows":
        raise Http404("windows endpoint requires os=windows")

    try:
        target_path = translate_path(tool_id, "skill", os, version.skill.name)
    except (KeyError, ValueError) as e:
        raise Http404(f"unknown tool or unsupported: {e}")

    target_path_expanded = _expand_target_path(target_path, platform)
    download_url = request.build_absolute_uri(reverse("install_zip", args=[token]))

    context = {
        "skill_name": version.skill.name,
        "version_no": version.version_no,
        "tool_id": tool_id,
        "os": os,
        "target_path": target_path,
        "target_path_expanded": target_path_expanded,
        "download_url": download_url,
    }

    body = render_to_string(PLATFORM_TEMPLATE[platform], context)
    _increment_install_count(version.skill_id)
    return HttpResponse(body, content_type=PLATFORM_CONTENT_TYPE[platform])


def install_zip_view(request, token):
    version = get_object_or_404(
        SkillVersion.objects.select_related("skill"),
        download_token=token,
        status=SkillVersion.STATUS_PUBLISHED,
        skill__is_listed=True,
        is_available=True,
    )
    _increment_install_count(version.skill_id)
    storage = get_storage()
    if settings.STORAGE_BACKEND == "local":
        # 本地存储：经 token 校验后由视图流式返回，不暴露 /media/
        # （prod DEBUG=False 下 Django 不 serve /media/，且直开 /media/ 会绕过 token）
        resp = HttpResponse(storage.get(version.file_path), content_type="application/zip")
        resp["Content-Disposition"] = f'attachment; filename="{version.skill.name}.zip"'
        return resp
    # 远程对象存储（OSS 等）：重定向到其 URL，下载交给对象存储
    return HttpResponseRedirect(storage.url(version.file_path))
