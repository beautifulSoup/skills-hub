"""轻量 zip 校验器 (D-T5-6)。

T5 阶段校验：
  (a) zipfile.ZipFile() 可打开
  (b) zip 含唯一根目录
  (c) 根目录下含 SKILL.md 文件

跟 T7 L1 机审（machine_review/l1.py::_check_zip_structure）语义对齐。
完整 L1+L2 校验（YAML frontmatter / 文件大小 / 密钥泄漏 / 危险 shell）由 T7 机审实施。
"""
import io
import zipfile


def _is_macos_metadata(name: str) -> bool:
    """过滤 macOS 打包产物 __MACOSX/ / .DS_Store。"""
    return name.startswith("__MACOSX/") or name.endswith(".DS_Store") or name.endswith("/.DS_Store")


def validate_skill_zip(content: bytes) -> tuple[bool, str]:
    """校验 content 是否为含唯一根目录 + 根目录下 SKILL.md 的合法 zip。

    例子（合法）：``<skill-name>/SKILL.md`` + 同根下其它文件 / 子目录。
    反例（拒绝）：zip 根直接 SKILL.md（缺包装目录）/ 多个根目录 / 根目录无 SKILL.md。

    Returns:
        (True, "") 通过；(False, error_msg) 失败。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return False, "上传的不是有效的 zip 文件"

    entries = [n for n in zf.namelist() if not _is_macos_metadata(n)]
    if not entries:
        return False, "zip 内无可见文件（或全部是 macOS 元数据）"

    # 唯一根目录：每个 entry 切第一个 / 取前段；所有 entry 必须共享同一个根
    roots = {name.split("/", 1)[0] for name in entries}
    if len(roots) != 1:
        return False, f"zip 必须含唯一根目录，当前发现 {len(roots)} 个：{sorted(roots)}"

    root = next(iter(roots))
    skill_md_name = f"{root}/SKILL.md"
    if not any(name == skill_md_name for name in entries):
        return False, f"根目录 {root}/ 必须含 SKILL.md 文件"

    return True, ""
