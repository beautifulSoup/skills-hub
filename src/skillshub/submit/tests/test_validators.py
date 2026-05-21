"""zip 校验器测试 — 跟 T7 L1 机审 spec 对齐：唯一根目录 + 根目录下 SKILL.md。"""
import io
import zipfile

from skillshub.submit.validators import validate_skill_zip


def make_test_zip(filenames: list[str]) -> bytes:
    """辅助：生成含指定文件的 in-memory zip bytes。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in filenames:
            zf.writestr(name, f"content of {name}")
    return buf.getvalue()


def test_valid_zip_with_wrapped_skill_md():
    """合法 zip：唯一根目录 + 根下 SKILL.md → (True, "")。"""
    content = make_test_zip([
        "report-assist/SKILL.md",
        "report-assist/README.md",
        "report-assist/scripts/run.py",
    ])
    ok, err = validate_skill_zip(content)
    assert ok is True
    assert err == ""


def test_bad_zip_format_rejected():
    """非 zip 文件（如 .txt）→ (False, 不是有效 zip)。"""
    content = b"this is not a zip file"
    ok, err = validate_skill_zip(content)
    assert ok is False
    assert "zip" in err.lower()


def test_zip_without_root_skill_md_rejected():
    """合法 zip 但根目录下无 SKILL.md → 必须含 SKILL.md 文件。"""
    content = make_test_zip(["report-assist/README.md", "report-assist/src/main.py"])
    ok, err = validate_skill_zip(content)
    assert ok is False
    assert "SKILL.md" in err


def test_zip_with_skill_md_at_top_level_rejected():
    """zip 根直接含 SKILL.md（缺包装目录）→ 必须有唯一根目录。"""
    content = make_test_zip(["SKILL.md", "README.md", "scripts/run.py"])
    ok, err = validate_skill_zip(content)
    assert ok is False
    # 多个 top-level entry（SKILL.md / README.md / scripts）→ "唯一根目录"
    assert "根目录" in err or "唯一" in err


def test_zip_with_multiple_root_dirs_rejected():
    """zip 含多个根目录 → 必须唯一根目录。"""
    content = make_test_zip(["foo/SKILL.md", "bar/SKILL.md"])
    ok, err = validate_skill_zip(content)
    assert ok is False
    assert "唯一" in err or "根目录" in err


def test_zip_with_macos_metadata_filtered():
    """zip 含 __MACOSX/ 元数据应被过滤，不影响合法结构判定。"""
    content = make_test_zip([
        "report-assist/SKILL.md",
        "report-assist/README.md",
        "__MACOSX/report-assist/._SKILL.md",
        "__MACOSX/._report-assist",
    ])
    ok, err = validate_skill_zip(content)
    assert ok is True, f"expected pass after filtering macOS metadata, got: {err}"
