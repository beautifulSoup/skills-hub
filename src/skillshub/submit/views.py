"""Submit app views。

URL 设计（D-T5-4, D-T5-8）：
  GET/POST /submit/       → submit_view（用 require_http_methods 分发）
  POST /skills/<skill_id>/versions/<version_id>/cancel → cancel_version
"""
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from skillshub.submit.forms import SubmitSkillForm
from skillshub.submit.models import SkillVersion
from skillshub.submit.services import (
    ConcurrentSubmissionError,
    SkillNameConflictError,
    create_skill_version,
    cancel_version as svc_cancel_version,
)

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET", "POST"])
def submit_view(request):
    """GET: 渲染提交表单；POST: 校验 + 创建 SkillVersion。

    ?skill=<name>（来自 owner detail 页「重新提交」按钮）→ name 字段锁定为该值，
    不能修改；服务层按相同 name 找到现有 Skill 并 +1 版本。
    """
    lock_name = request.GET.get("skill") or None

    if request.method == "GET":
        form = SubmitSkillForm(lock_name=lock_name)
        return render(request, "submit/submit.html", {
            "form": form,
            "lock_name": lock_name,
        })

    # POST
    form = SubmitSkillForm(request.POST, request.FILES, lock_name=lock_name)
    if not form.is_valid():
        return render(request, "submit/submit.html", {
            "form": form,
            "lock_name": lock_name,
        })

    name = form.cleaned_data["name"]
    description = form.cleaned_data["description"]
    readme = form.cleaned_data["readme"]
    tags = form.cleaned_data["tags"]
    content_file = form.cleaned_data["content"]
    content_bytes = content_file.read()

    try:
        create_skill_version(
            submitter=request.user,
            name=name,
            description=description,
            readme=readme,
            tags=tags,
            content_bytes=content_bytes,
        )
    except ConcurrentSubmissionError as e:
        form.add_error(None, str(e))
        return render(request, "submit/submit.html", {"form": form})
    except SkillNameConflictError as e:
        form.add_error("name", str(e))
        return render(request, "submit/submit.html", {
            "form": form,
            "lock_name": lock_name,
        })
    except ValidationError as e:
        form.add_error("content", e)
        return render(request, "submit/submit.html", {"form": form})

    return redirect(f"/submit/?ok=1&name={name}")


@login_required
@require_POST
def cancel_version(request, skill_id: int, version_id: int):
    """POST /skills/<skill_id>/versions/<version_id>/cancel

    校验 version.skill_id == skill_id (D-T5-8)，再调服务层 cancel。
    """
    version = get_object_or_404(SkillVersion, pk=version_id)
    if version.skill_id != skill_id:
        from django.http import Http404
        raise Http404("版本不属于该 Skill。")

    try:
        svc_cancel_version(request.user, version)
    except PermissionDenied as e:
        return HttpResponseForbidden(str(e))
    except ValueError as e:
        return HttpResponseBadRequest(str(e))

    return redirect("/submit/?cancelled=1")
