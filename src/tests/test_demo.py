"""demo task + view 测试。"""
import json
import pytest

pytestmark = pytest.mark.django_db


def test_add_task_returns_sum():
    from skillshub.demo.tasks import add
    result = add.delay(2, 3)  # EAGER 模式同步返回
    assert result.get(timeout=5) == 5


def test_demo_view_enqueues_and_returns_task_id(client):
    resp = client.get("/demo/?x=2&y=3")
    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert "task_id" in body


def test_demo_result_view_returns_success_for_completed_task(client):
    """EAGER 模式下任务立即完成，应返回 SUCCESS + result。"""
    enqueue_resp = client.get("/demo/?x=10&y=20")
    task_id = json.loads(enqueue_resp.content)["task_id"]

    result_resp = client.get(f"/demo/{task_id}")
    assert result_resp.status_code == 200
    body = json.loads(result_resp.content)
    assert body["status"] == "SUCCESS"
    assert body["result"] == 30
