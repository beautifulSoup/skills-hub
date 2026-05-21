"""healthz endpoint 测试。"""
import json
import pytest

pytestmark = pytest.mark.django_db


def test_healthz_returns_200_with_ok_status(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["redis"] == "ok"
