"""tools.translate_path 测试 (T10)."""
import pytest

from skillshub.tools.registry import translate_path


def test_claude_code_skill_macos():
    assert translate_path("claude-code", "skill", "macos", "foo") == "~/.claude/skills/foo/"


def test_claude_code_skill_linux():
    assert translate_path("claude-code", "skill", "linux", "foo") == "~/.claude/skills/foo/"


def test_claude_code_skill_windows():
    p = translate_path("claude-code", "skill", "windows", "foo")
    assert p == "%USERPROFILE%\\.claude\\skills\\foo\\"


def test_workbuddy_skill_linux():
    assert translate_path("workbuddy", "skill", "linux", "foo") == "~/.workbuddy/skills/foo/"


def test_workbuddy_skill_windows():
    p = translate_path("workbuddy", "skill", "windows", "foo")
    assert p == "%USERPROFILE%\\.workbuddy\\skills\\foo\\"


def test_unknown_tool_raises():
    with pytest.raises((KeyError, ValueError)):
        translate_path("not-a-real-tool", "skill", "linux", "foo")
