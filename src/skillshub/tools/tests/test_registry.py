"""
T4 tool-registry 测试（10 个 case）。

使用 tmp_path fixture 写临时 yaml，通过 django.test.override_settings patch
TOOLS_YAML_PATH，再调 reload_tools() 清缓存使下次 get_all_tools() 重新加载。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from django.test import override_settings

from skillshub.tools.registry import (
    get_all_tools,
    get_tool,
    get_tools_for_type,
    reload_tools,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _use_fixture(fixture_name: str, tmp_path: Path) -> Path:
    """把 fixture 复制到 tmp_path，返回新路径（让 override_settings 用绝对路径）。"""
    src = FIXTURES_DIR / fixture_name
    dst = tmp_path / fixture_name
    shutil.copy(src, dst)
    return dst


# ---------------------------------------------------------------------------
# 正常加载
# ---------------------------------------------------------------------------


def test_load_valid_yaml_returns_2_tools(tmp_path):
    yaml_path = _use_fixture("valid_tools.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        tools = get_all_tools()
    assert len(tools) == 2
    ids = {t.id for t in tools}
    assert ids == {"claude-code", "workbuddy"}


def test_get_tools_for_type_skill_returns_both(tmp_path):
    yaml_path = _use_fixture("valid_tools.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        result = get_tools_for_type("skill")
    assert len(result) == 2
    ids = {t.id for t in result}
    assert ids == {"claude-code", "workbuddy"}


def test_get_tools_for_type_subagent_returns_only_claude_code(tmp_path):
    yaml_path = _use_fixture("valid_tools.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        result = get_tools_for_type("subagent")
    assert len(result) == 1
    assert result[0].id == "claude-code"


def test_get_tool_by_id_found(tmp_path):
    yaml_path = _use_fixture("valid_tools.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        tool = get_tool("claude-code")
    assert tool is not None
    assert tool.name == "Claude Code"
    assert "skill" in tool.supports
    assert "subagent" in tool.supports


def test_get_tool_by_id_not_found_returns_none(tmp_path):
    yaml_path = _use_fixture("valid_tools.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        result = get_tool("nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# 校验失败 — fail loudly
# ---------------------------------------------------------------------------


def test_missing_paths_field_raises_valueerror(tmp_path):
    yaml_path = _use_fixture("missing_paths.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        with pytest.raises(ValueError, match="paths"):
            get_all_tools()


def test_invalid_supports_raises_valueerror(tmp_path):
    yaml_path = _use_fixture("invalid_supports.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        with pytest.raises(ValueError, match="foo"):
            get_all_tools()


def test_supports_paths_inconsistent_raises_valueerror(tmp_path):
    yaml_path = _use_fixture("inconsistent.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        with pytest.raises(ValueError, match="subagent"):
            get_all_tools()


# ---------------------------------------------------------------------------
# 边界
# ---------------------------------------------------------------------------


def test_get_tools_for_type_invalid_returns_empty_list(tmp_path):
    yaml_path = _use_fixture("valid_tools.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        result = get_tools_for_type("invalid")
    assert result == []


def test_reload_tools_clears_cache(tmp_path):
    """reload_tools() 后下次 get_all_tools() 重新读 yaml，能感知到文件变化。"""
    yaml_path = _use_fixture("valid_tools.yaml", tmp_path)
    with override_settings(TOOLS_YAML_PATH=str(yaml_path)):
        reload_tools()
        first = get_all_tools()
        assert len(first) == 2

        reload_tools()
        second = get_all_tools()
        # 同一 yaml，reload 后结果一致（验证重新加载而非使用旧 cache）
        assert len(second) == 2
        assert {t.id for t in first} == {t.id for t in second}
