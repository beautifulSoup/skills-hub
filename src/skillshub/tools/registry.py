"""
工具注册表 — lazy 加载 + 模块级缓存（D-T4-1 / D-T4-4）。

公开 API：
    get_all_tools()           -> list[Tool]
    get_tools_for_type(type)  -> list[Tool]
    get_tool(tool_id)         -> Tool | None
    reload_tools()            -> None  （清缓存，测试 / 热更新用）
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

from .models import VALID_CONTENT_TYPES, Tool

if TYPE_CHECKING:
    pass

# 模块级缓存；None 表示尚未加载（D-T4-1）
_TOOLS_CACHE: list[Tool] | None = None

REQUIRED_FIELDS = ("id", "name", "supports", "paths", "install_methods")


def _load_tools() -> list[Tool]:
    """从 settings.TOOLS_YAML_PATH 读取并校验工具清单（D-T4-3 / D-T4-5）。"""
    from django.conf import settings  # 延迟导入，避免 import-time Django setup

    yaml_path = Path(settings.TOOLS_YAML_PATH)
    if not yaml_path.exists():
        raise FileNotFoundError(f"tools.yaml not found: {yaml_path}")

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("tools.yaml must be a YAML list at root level")

    tools: list[Tool] = []
    for entry in raw:
        entry_id = entry.get("id", "<unknown>")

        # 必填字段检查
        for field in REQUIRED_FIELDS:
            if field not in entry:
                raise ValueError(
                    f"Tool entry '{entry_id}': missing required field '{field}'"
                )

        # supports 合法值检查
        supports_list: list[str] = entry["supports"]
        for s in supports_list:
            if s not in VALID_CONTENT_TYPES:
                raise ValueError(
                    f"Tool entry '{entry_id}': invalid supports value '{s}'. "
                    f"Allowed: {sorted(VALID_CONTENT_TYPES)}"
                )

        # supports 与 paths 一致性检查
        paths: dict[str, str] = entry["paths"]
        for s in supports_list:
            if s not in paths:
                raise ValueError(
                    f"Tool entry '{entry_id}': supports declares '{s}' "
                    f"but paths has no '{s}' key"
                )

        tools.append(
            Tool(
                id=entry["id"],
                name=entry["name"],
                supports=tuple(supports_list),
                paths=dict(paths),
                install_methods=tuple(entry["install_methods"]),
            )
        )

    return tools


def get_all_tools() -> list[Tool]:
    """返回所有工具（lazy load + cache，D-T4-1）。"""
    global _TOOLS_CACHE
    if _TOOLS_CACHE is None:
        _TOOLS_CACHE = _load_tools()
    return _TOOLS_CACHE


def get_tools_for_type(content_type: str) -> list[Tool]:
    """返回 supports 含 content_type 的工具列表；非法 type 静默返回空列表（D-T4-4）。"""
    return [t for t in get_all_tools() if content_type in t.supports]


def get_tool(tool_id: str) -> Tool | None:
    """按 id 查工具，不存在返回 None（D-T4-4）。"""
    for t in get_all_tools():
        if t.id == tool_id:
            return t
    return None


def reload_tools() -> None:
    """清空缓存，下次调用触发重新加载（测试 + 二期热更新用）。"""
    global _TOOLS_CACHE
    _TOOLS_CACHE = None


# ---------------------------------------------------------------------------
# T10：路径翻译 + 工具筛选
# ---------------------------------------------------------------------------

OsLiteral = Literal["linux", "macos", "windows"]


def translate_path(
    tool_id: str, content_type: str, os: OsLiteral, skill_name: str
) -> str:
    """把 tools.yaml 的 unix-style 路径模板翻译到目标 OS 表达。

    linux/macos: 保留 ~/...
    windows:     ~ → %USERPROFILE%；/ → \\
    """
    tool = get_tool(tool_id)
    if tool is None:
        raise KeyError(f"tool '{tool_id}' not in tools.yaml")

    template = tool.paths.get(content_type)
    if template is None:
        raise ValueError(
            f"tool '{tool_id}' does not support content_type '{content_type}'"
        )

    rendered = template.replace("{name}", skill_name)
    if os in ("linux", "macos"):
        return rendered
    if os == "windows":
        rendered = rendered.replace("~", "%USERPROFILE%")
        rendered = rendered.replace("/", "\\")
        return rendered
    raise ValueError(f"unsupported os: {os}")


def list_supported(content_type: str) -> list[dict]:
    """返回 supports 含 content_type 的所有工具（保持 tools.yaml 顺序）。

    返回 [{"id": "claude-code", "name": "Claude Code"}, ...]
    """
    return [
        {"id": t.id, "name": t.name}
        for t in get_all_tools()
        if content_type in t.supports
    ]
