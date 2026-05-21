"""L1 检查单元测试。"""
from __future__ import annotations

import io
import zipfile

import pytest
from django.contrib.auth import get_user_model

from skillshub.submit.machine_review import l1
from skillshub.submit.machine_review.violations import (
    L1_EXTENSION_WHITELIST,
    L1_NAME_COLLISION,
    L1_NAME_FORMAT,
    L1_SIZE_LIMIT,
    L1_SKILL_MD_FRONTMATTER,
    L1_ZIP_STRUCTURE,
)
from skillshub.submit.models import Skill


# L1.run 内 _check_name_collision 任意调用都触发 DB（manifest 解析成功后必跑）。
# 模块级 mark 让所有 L1 测试都拿到 DB 访问权限；不再在 production code 里做静默跳过。
pytestmark = pytest.mark.django_db


def make_zip(entries: dict[str, bytes | str]) -> bytes:
    """构造 in-memory zip。entries: {path: content_bytes_or_str}。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    return buf.getvalue()


VALID_FRONTMATTER = b"---\nname: my-skill\ndescription: example skill\n---\n# Heading\nbody"


class _FakeVersion:
    """用 in-memory 假 version 跑 L1 不依赖 DB；name_collision 测试单独走 DB。"""
    def __init__(self, skill_id: int = 1):
        self.skill_id = skill_id


# ─── zip_structure ───
def test_l1_zip_structure_passes_single_root():
    content = make_zip({"myskill/SKILL.md": VALID_FRONTMATTER, "myskill/foo.md": "x"})
    violations = l1.run(content, _FakeVersion())
    assert not [v for v in violations if v.code == L1_ZIP_STRUCTURE]


def test_l1_zip_structure_fails_no_root_skill_md():
    content = make_zip({"myskill/foo.md": "x"})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_ZIP_STRUCTURE]


def test_l1_zip_structure_fails_multiple_roots():
    content = make_zip({"a/SKILL.md": VALID_FRONTMATTER, "b/foo.md": "x"})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_ZIP_STRUCTURE]


def test_l1_zip_structure_ignores_macos_metadata():
    content = make_zip({
        "myskill/SKILL.md": VALID_FRONTMATTER,
        "__MACOSX/myskill/._SKILL.md": b"",
        "myskill/.DS_Store": b"",
    })
    violations = l1.run(content, _FakeVersion())
    assert not [v for v in violations if v.code == L1_ZIP_STRUCTURE]


def test_l1_zip_structure_fails_corrupt_zip():
    violations = l1.run(b"this is not a zip", _FakeVersion())
    assert len(violations) == 1
    assert violations[0].code == L1_ZIP_STRUCTURE


# ─── frontmatter ───
def test_l1_frontmatter_passes_valid():
    content = make_zip({"myskill/SKILL.md": VALID_FRONTMATTER})
    violations = l1.run(content, _FakeVersion())
    assert not [v for v in violations if v.code == L1_SKILL_MD_FRONTMATTER]


def test_l1_frontmatter_fails_no_frontmatter():
    content = make_zip({"myskill/SKILL.md": b"# just a heading no frontmatter"})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_SKILL_MD_FRONTMATTER]


def test_l1_frontmatter_fails_yaml_error():
    bad = b"---\nname: : :\ndescription: x\n---\nbody"
    content = make_zip({"myskill/SKILL.md": bad})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_SKILL_MD_FRONTMATTER]


def test_l1_frontmatter_fails_missing_name():
    content = make_zip({"myskill/SKILL.md": b"---\ndescription: x\n---\nbody"})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_SKILL_MD_FRONTMATTER]


def test_l1_frontmatter_fails_missing_description():
    content = make_zip({"myskill/SKILL.md": b"---\nname: x\n---\nbody"})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_SKILL_MD_FRONTMATTER]


def test_l1_frontmatter_handles_unicode_decode_error():
    # 0xff 0xfe 不是合法 UTF-8 起始
    content = make_zip({"myskill/SKILL.md": b"\xff\xfe\xfd"})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_SKILL_MD_FRONTMATTER]


# ─── name_format ───
def test_l1_name_format_passes_valid_slug():
    fm = b"---\nname: my-cool-skill-2\ndescription: x\n---\n"
    content = make_zip({"myskill/SKILL.md": fm})
    violations = l1.run(content, _FakeVersion())
    assert not [v for v in violations if v.code == L1_NAME_FORMAT]


def test_l1_name_format_fails_uppercase():
    fm = b"---\nname: MySkill\ndescription: x\n---\n"
    content = make_zip({"myskill/SKILL.md": fm})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_NAME_FORMAT]


def test_l1_name_format_fails_underscore():
    fm = b"---\nname: my_skill\ndescription: x\n---\n"
    content = make_zip({"myskill/SKILL.md": fm})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_NAME_FORMAT]


def test_l1_name_format_fails_too_short():
    fm = b"---\nname: ab\ndescription: x\n---\n"
    content = make_zip({"myskill/SKILL.md": fm})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_NAME_FORMAT]


def test_l1_name_format_fails_too_long():
    long = "x" * 51
    fm = f"---\nname: {long}\ndescription: x\n---\n".encode()
    content = make_zip({"myskill/SKILL.md": fm})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_NAME_FORMAT]


# ─── name_collision ───（DB 测试）
@pytest.mark.django_db
def test_l1_name_collision_same_skill_no_violation():
    """同 skill_id 的 version 不报冲突（exclude self）。"""
    User = get_user_model()
    u = User.objects.create_user(username="u", email="u@e.com", password="x")
    s = Skill.objects.create(name="my-skill", description="d", created_by=u)
    fm = b"---\nname: my-skill\ndescription: x\n---\n"
    content = make_zip({"myskill/SKILL.md": fm})
    version = _FakeVersion(skill_id=s.id)
    violations = l1.run(content, version)
    assert not [v for v in violations if v.code == L1_NAME_COLLISION]


@pytest.mark.django_db
def test_l1_name_collision_different_skill_violation():
    """不同 skill_id 同名报冲突。"""
    User = get_user_model()
    u = User.objects.create_user(username="u2", email="u2@e.com", password="x")
    Skill.objects.create(name="taken-name", description="d", created_by=u)
    fm = b"---\nname: taken-name\ndescription: x\n---\n"
    content = make_zip({"myskill/SKILL.md": fm})
    # 假 version skill_id=999（不同于已存在的 skill）
    violations = l1.run(content, _FakeVersion(skill_id=999))
    assert [v for v in violations if v.code == L1_NAME_COLLISION]


# ─── size_limit ───
def test_l1_size_limit_passes_small_files():
    content = make_zip({"myskill/SKILL.md": VALID_FRONTMATTER, "myskill/foo.md": "x" * 100})
    violations = l1.run(content, _FakeVersion())
    assert not [v for v in violations if v.code == L1_SIZE_LIMIT]


def test_l1_size_limit_fails_single_file_over_5mb():
    # 6 MB 文件
    big = b"x" * (6 * 1024 * 1024)
    content = make_zip({"myskill/SKILL.md": VALID_FRONTMATTER, "myskill/big.md": big})
    violations = l1.run(content, _FakeVersion())
    size_v = [v for v in violations if v.code == L1_SIZE_LIMIT]
    assert size_v
    assert any("big.md" in v.location for v in size_v)


def test_l1_size_limit_fails_total_over_20mb():
    # 5 个 5 MB - 1 byte 文件 = 25 MB - 5 bytes 总；每个文件本身刚不超单文件上限
    five_mb_minus = b"x" * (5 * 1024 * 1024 - 1)
    content = make_zip({
        "myskill/SKILL.md": VALID_FRONTMATTER,
        "myskill/a.md": five_mb_minus,
        "myskill/b.md": five_mb_minus,
        "myskill/c.md": five_mb_minus,
        "myskill/d.md": five_mb_minus,
        "myskill/e.md": five_mb_minus,
    })
    violations = l1.run(content, _FakeVersion())
    size_v = [v for v in violations if v.code == L1_SIZE_LIMIT]
    assert any(v.location == "archive" for v in size_v), f"got {[v.location for v in size_v]}"


# ─── extension_whitelist ───
def test_l1_extension_passes_whitelist():
    content = make_zip({
        "myskill/SKILL.md": VALID_FRONTMATTER,
        "myskill/script.py": "x",
        "myskill/config.yaml": "x",
    })
    violations = l1.run(content, _FakeVersion())
    assert not [v for v in violations if v.code == L1_EXTENSION_WHITELIST]


def test_l1_extension_fails_unknown_suffix():
    content = make_zip({"myskill/SKILL.md": VALID_FRONTMATTER, "myskill/binary.exe": b"\x00"})
    violations = l1.run(content, _FakeVersion())
    ext_v = [v for v in violations if v.code == L1_EXTENSION_WHITELIST]
    assert ext_v
    assert any("binary.exe" in v.location for v in ext_v)


def test_l1_extension_fails_image():
    content = make_zip({"myskill/SKILL.md": VALID_FRONTMATTER, "myskill/logo.png": b"\x89PNG"})
    violations = l1.run(content, _FakeVersion())
    assert [v for v in violations if v.code == L1_EXTENSION_WHITELIST]


# ─── 集成（多 violation 一次跑出）───
def test_l1_collects_multiple_violations_in_one_pass():
    """坏 zip 多问题一次输出全部，不短路。"""
    bad_fm = b"---\nname: BadName\n---\nbody"  # 缺 description + name 大写
    content = make_zip({
        "myskill/SKILL.md": bad_fm,
        "myskill/binary.exe": b"x",
    })
    violations = l1.run(content, _FakeVersion())
    codes = {v.code for v in violations}
    assert L1_SKILL_MD_FRONTMATTER in codes  # 缺 description
    assert L1_NAME_FORMAT in codes            # 大写
    assert L1_EXTENSION_WHITELIST in codes    # .exe
