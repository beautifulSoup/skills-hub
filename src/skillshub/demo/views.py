"""Demo views：触发 add task + 查结果。"""
from django.http import JsonResponse, HttpResponseBadRequest
from celery.result import AsyncResult

from skillshub.demo.tasks import add


def enqueue_add(request):
    """GET /demo/?x=&y=  → 入队 add(x, y) → 返回 task_id"""
    try:
        x = int(request.GET.get("x", "0"))
        y = int(request.GET.get("y", "0"))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("x and y must be integers")

    async_result = add.delay(x, y)
    return JsonResponse({"task_id": async_result.id})


def get_result(request, task_id: str):
    """GET /demo/<task_id>  → 查 result_backend → 返回 status / result"""
    async_result = AsyncResult(task_id)
    payload = {"status": async_result.status}
    if async_result.successful():
        payload["result"] = async_result.result
    elif async_result.failed():
        payload["error"] = str(async_result.result)
    return JsonResponse(payload)
