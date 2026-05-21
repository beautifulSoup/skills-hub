"""L1 结构合法性检查 — 6 项纯函数 + run() 编排。

依赖：
- PyYAML（仓库已装）
- skillshub.submit.models.Skill（仅 _check_name_collision 用 DB）
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Optional

import yaml

from skillshub.submit.machine_review.violations import (
    EXTENSION_WHITELIST,
    L1_EXTENSION_WHITELIST,
    L1_NAME_COLLISION,
    L1_NAME_FORMAT,
    L1_SIZE_LIMIT,
    L1_SKILL_MD_FRONTMATTER,
    L1_ZIP_STRUCTURE,
    MAX_FILE_SIZE,
    MAX_TOTAL_SIZE,
    Violation,
    is_macos_metadata,
)

_NAME_RE = re.compile(r"^[a-z0-9-]{3,50}$")
_FRONTMATTER_RE = re.compile(rb"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _real_entries(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """返回非 macOS 元数据 entry。"""
    return [info for info in zf.infolist() if not is_macos_metadata(info.filename)]


def _check_zip_structure(zf: zipfile.ZipFile) -> tuple[Optional[str], list[Violation]]:
    """检查单根目录 + 根 SKILL.md。返回 (root_dir | None, violations)。"""
    violations: list[Violation] = []
    entries = _real_entries(zf)
    if not entries:
        violations.append(Violation(
            code=L1_ZIP_STRUCTURE, severity="error", location="archive",
            message="zip 内无可见文件（或全部是 macOS 元数据）",
        ))
        return None, violations

    # 单文件无目录时根 = 文件名本身；带目录时根 = 第一段路径
    roots = {info.filename.split("/", 1)[0] for info in entries}
    if len(roots) != 1:
        violations.append(Violation(
            code=L1_ZIP_STRUCTURE, severity="error", location="archive",
            message=f"zip 必须含唯一根目录，当前发现 {len(roots)} 个：{sorted(roots)}",
        ))
        return None, violations

    root = next(iter(roots))
    skill_md_name = f"{root}/SKILL.md"
    has_skill_md = any(info.filename == skill_md_name for info in entries)
    if not has_skill_md:
        violations.append(Violation(
            code=L1_ZIP_STRUCTURE, severity="error", location=f"{root}/",
            message=f"根目录 {root}/ 必须含 SKILL.md 文件",
        ))
        return None, violations

    return root, violations


def _try_parse_skill_md(zf: zipfile.ZipFile, root: str) -> tuple[Optional[dict], list[Violation]]:
    """解析 SKILL.md frontmatter；失败抓为 violation。"""
    violations: list[Violation] = []
    try:
        raw = zf.read(f"{root}/SKILL.md")
    except KeyError:
        violations.append(Violation(
            code=L1_SKILL_MD_FRONTMATTER, severity="error", location=f"{root}/SKILL.md",
            message="读不到 SKILL.md（zip 损坏？）",
        ))
        return None, violations

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        violations.append(Violation(
            code=L1_SKILL_MD_FRONTMATTER, severity="error", location=f"{root}/SKILL.md:1",
            message="SKILL.md 不是合法 UTF-8 编码",
        ))
        return None, violations

    m = _FRONTMATTER_RE.match(text.encode("utf-8"))
    if not m:
        violations.append(Violation(
            code=L1_SKILL_MD_FRONTMATTER, severity="error", location=f"{root}/SKILL.md:1",
            message="SKILL.md 必须以 --- 包裹的 YAML frontmatter 开头",
        ))
        return None, violations

    try:
        manifest = yaml.safe_load(m.group(1).decode("utf-8"))
    except yaml.YAMLError as e:
        violations.append(Violation(
            code=L1_SKILL_MD_FRONTMATTER, severity="error", location=f"{root}/SKILL.md:1",
            message=f"YAML frontmatter 解析失败：{e}",
        ))
        return None, violations

    if not isinstance(manifest, dict):
        violations.append(Violation(
            code=L1_SKILL_MD_FRONTMATTER, severity="error", location=f"{root}/SKILL.md:1",
            message="frontmatter 必须是 YAML 映射（含 name/description 字段）",
        ))
        return None, violations

    if not manifest.get("name"):
        violations.append(Violation(
            code=L1_SKILL_MD_FRONTMATTER, severity="error", location=f"{root}/SKILL.md:1",
            message="frontmatter 缺 name 字段（或为空）",
        ))
    if not manifest.get("description"):
        violations.append(Violation(
            code=L1_SKILL_MD_FRONTMATTER, severity="error", location=f"{root}/SKILL.md:1",
            message="frontmatter 缺 description 字段（或为空）",
        ))

    # name + description 都缺时仍返回 manifest dict，让上层 size/extension 检查继续
    # 但若 name 缺，后续 _check_name_format 会被 skip（caller 判断）
    return manifest, violations


def _check_name_format(manifest: dict, root: str) -> list[Violation]:
    name = manifest.get("name")
    if not name or not isinstance(name, str):
        return []  # 已被 frontmatter 检查捕获
    if not _NAME_RE.match(name):
        return [Violation(
            code=L1_NAME_FORMAT, severity="error", location=f"{root}/SKILL.md:1",
            message=f"name='{name}' 不合法：必须为 3-50 字符的小写字母/数字/短横线",
        )]
    return []


def _check_name_collision(manifest: dict, version, root: str) -> list[Violation]:
    """name 全局唯一（exclude 自身 skill_id）。"""
    from skillshub.submit.models import Skill  # 局部 import 防 app loading 循环

    name = manifest.get("name")
    if not name or not isinstance(name, str):
        return []
    conflict = (
        Skill.objects
        .filter(name=name)
        .exclude(id=version.skill_id)
        .exists()
    )
    if conflict:
        return [Violation(
            code=L1_NAME_COLLISION, severity="error", location=f"{root}/SKILL.md:1",
            message=f"name='{name}' 与已有 Skill 同名（hub 内全局唯一）",
        )]
    return []


def _check_size_limits(zf: zipfile.ZipFile) -> list[Violation]:
    violations: list[Violation] = []
    total = 0
    for info in _real_entries(zf):
        if info.is_dir():
            continue
        if info.file_size > MAX_FILE_SIZE:
            violations.append(Violation(
                code=L1_SIZE_LIMIT, severity="error", location=info.filename,
                message=f"文件超过单文件 5 MB 上限（解压后 {info.file_size} 字节）",
            ))
        total += info.file_size
    if total > MAX_TOTAL_SIZE:
        violations.append(Violation(
            code=L1_SIZE_LIMIT, severity="error", location="archive",
            message=f"解压后总大小 {total} 字节，超过 20 MB 上限",
        ))
    return violations


def _check_extension_whitelist(zf: zipfile.ZipFile) -> list[Violation]:
    violations: list[Violation] = []
    for info in _real_entries(zf):
        if info.is_dir():
            continue
        basename = info.filename.rsplit("/", 1)[-1]
        if "." not in basename:
            ext = ""
        else:
            ext = "." + basename.rsplit(".", 1)[-1].lower()
        if ext not in EXTENSION_WHITELIST:
            violations.append(Violation(
                code=L1_EXTENSION_WHITELIST, severity="error", location=info.filename,
                message=f"文件后缀 '{ext or '<无>'}' 不在白名单（{sorted(EXTENSION_WHITELIST)}）",
            ))
    return violations


def run(content: bytes, version) -> list[Violation]:
    """L1 全部检查；不短路全跑完。

    Args:
        content: zip bytes
        version: SkillVersion 实例（用于 name 全局唯一查询的 skill_id）
    """
    violations: list[Violation] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return [Violation(
            code=L1_ZIP_STRUCTURE, severity="error", location="archive",
            message="上传的不是合法 zip 文件",
        )]

    with zf:
        root, struct_violations = _check_zip_structure(zf)
        violations.extend(struct_violations)
        violations.extend(_check_size_limits(zf))
        violations.extend(_check_extension_whitelist(zf))

        if root is not None:
            manifest, fm_violations = _try_parse_skill_md(zf, root)
            violations.extend(fm_violations)
            if manifest is not None:
                # spec: name_collision 仅在 name_format 通过时执行
                fmt_violations = _check_name_format(manifest, root)
                violations.extend(fmt_violations)
                if not fmt_violations:
                    violations.extend(_check_name_collision(manifest, version, root))

    return violations
