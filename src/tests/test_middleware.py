"""RequestIdMiddleware 测试。"""
import re
import pytest
from django.test import RequestFactory
from skillshub.core.middleware import RequestIdMiddleware

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def get_response():
    def _resp(request):
        from django.http import HttpResponse
        return HttpResponse("ok")
    return _resp


def test_middleware_generates_request_id_when_header_absent(get_response):
    middleware = RequestIdMiddleware(get_response)
    request = RequestFactory().get("/")
    middleware(request)
    assert hasattr(request, "request_id")
    assert UUID_RE.match(request.request_id)


def test_middleware_reuses_request_id_from_header(get_response):
    middleware = RequestIdMiddleware(get_response)
    request = RequestFactory().get("/", HTTP_X_REQUEST_ID="my-existing-id-123")
    middleware(request)
    assert request.request_id == "my-existing-id-123"


def test_middleware_sets_response_header(get_response):
    middleware = RequestIdMiddleware(get_response)
    request = RequestFactory().get("/")
    response = middleware(request)
    assert response["X-Request-ID"] == request.request_id
