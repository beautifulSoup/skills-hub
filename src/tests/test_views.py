"""核心 view 测试（除 healthz 外）。"""
import pytest

pytestmark = pytest.mark.django_db


def test_index_returns_200_with_brand_text(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"skills-hub" in resp.content
    assert b"Skill Repository" in resp.content


def test_index_includes_tailwind_class(client):
    """验证 base.html 链路 + 模板用了 Tailwind class。"""
    resp = client.get("/")
    assert b"font-bold" in resp.content or b"font-extrabold" in resp.content
