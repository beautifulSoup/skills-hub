"""HTTP 中间件。"""
import uuid


class RequestIdMiddleware:
    """注入 request_id 到 request 与 response header。

    优先从 X-Request-ID header 取（外部 trace 透传），否则生成 UUIDv4。
    """

    HEADER_NAME = "X-Request-ID"
    META_KEY = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from skillshub.core.logging_conf import set_request_id

        request.request_id = request.META.get(self.META_KEY) or str(uuid.uuid4())
        set_request_id(request.request_id)
        try:
            response = self.get_response(request)
        finally:
            set_request_id("-")  # 清理，避免跨请求泄漏
        response[self.HEADER_NAME] = request.request_id
        return response
