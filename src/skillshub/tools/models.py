"""
Tool dataclass — 纯内存，不入 DB（D-T4-1 / D-T4-2）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ContentType = Literal["skill", "subagent"]
InstallMethod = Literal["cli", "ai_paste", "manual"]

VALID_CONTENT_TYPES: frozenset[str] = frozenset({"skill", "subagent"})
VALID_INSTALL_METHODS: frozenset[str] = frozenset({"cli", "ai_paste", "manual"})


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    supports: tuple[str, ...]          # e.g. ("skill", "subagent")
    paths: dict[str, str]              # e.g. {"skill": "~/.claude/skills/{name}/"}
    install_methods: tuple[str, ...]   # e.g. ("cli", "ai_paste", "manual")
