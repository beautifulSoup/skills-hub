"""L2 安全扫描 — 密钥正则 + 危险 shell + Python AST。"""
from __future__ import annotations

import ast
import io
import re
import zipfile
from typing import Iterator

from skillshub.submit.machine_review.violations import (
    EXTENSION_WHITELIST,
    L2_DANGEROUS_SHELL_BASE64_PIPE_SH,
    L2_DANGEROUS_SHELL_CURL_PIPE_SH,
    L2_DANGEROUS_SHELL_EVAL,
    L2_DANGEROUS_SHELL_RM_RF_ROOT,
    L2_PYTHON_COMPILE,
    L2_PYTHON_EVAL,
    L2_PYTHON_EXEC,
    L2_PYTHON_SYNTAX_ERROR,
    L2_SECRET_ANTHROPIC_API_KEY,
    L2_SECRET_AWS_ACCESS_KEY,
    L2_SECRET_AWS_SECRET_KEY,
    L2_SECRET_GCP_SERVICE_ACCOUNT,
    L2_SECRET_GITHUB_FINE_GRAINED,
    L2_SECRET_GITHUB_PAT,
    L2_SECRET_OPENAI_API_KEY,
    L2_SECRET_SSH_PRIVATE_KEY,
    Violation,
    is_macos_metadata,
)

# ── 密钥正则集 ─────────────────────────────────────────────
# NOTE: Anthropic 形如 sk-ant-... 的 token 会同时命中 OPENAI 和 ANTHROPIC 两条规则。
# 这是有意设计：宁可两条 violation 也比漏报强；T8 人审看到任一条都会拒绝。
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    (L2_SECRET_AWS_ACCESS_KEY, re.compile(r"(?<![A-Z0-9])(AKIA|ASIA)[0-9A-Z]{16}(?![A-Z0-9])")),
    (L2_SECRET_AWS_SECRET_KEY, re.compile(r"""aws_secret_access_key\s*[:=]\s*["']?[A-Za-z0-9/+=]{40}["']?""", re.IGNORECASE)),
    (L2_SECRET_OPENAI_API_KEY, re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b")),
    (L2_SECRET_ANTHROPIC_API_KEY, re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    (L2_SECRET_GITHUB_PAT, re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    (L2_SECRET_GITHUB_FINE_GRAINED, re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b")),
    # 涵盖 OpenSSH / RSA / EC / DSA / PGP / PKCS#8 (BEGIN PRIVATE KEY) /
    # ENCRYPTED PRIVATE KEY 等格式；现代工具默认 PKCS#8。
    (L2_SECRET_SSH_PRIVATE_KEY, re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
]

# GCP service account 启发：单文件需同时含两个关键字段
_GCP_SA_TYPE = re.compile(r'"type"\s*:\s*"service_account"')
_GCP_SA_PRIVATE_KEY = re.compile(r'"private_key"\s*:')

# ── 危险 shell 模式 ─────────────────────────────────────────
_SHELL_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # (code, severity, pattern)
    (L2_DANGEROUS_SHELL_RM_RF_ROOT, "error",
     re.compile(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+(/(?!\w)|/\*|\$HOME|~)")),
    (L2_DANGEROUS_SHELL_CURL_PIPE_SH, "warning",
     re.compile(r"\b(curl|wget)\s+[^\|\n]*\|\s*(sh|bash|zsh)\b")),
    (L2_DANGEROUS_SHELL_BASE64_PIPE_SH, "warning",
     re.compile(r"\bbase64\s+-d[^\|\n]*\|\s*(sh|bash|zsh)\b")),
    # eval 后接 ", ', $, 或 ` (反引号 — 命令替换；攻击常见写法)
    (L2_DANGEROUS_SHELL_EVAL, "warning",
     re.compile(r"\beval\s+[\"'$`]")),
]

# ── markdown 围栏识别 ─────────────────────────────────────
_FENCE_OPEN_RE = re.compile(r"^```\s*(sh|bash|zsh)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")


def _read_text(zf: zipfile.ZipFile, name: str) -> str | None:
    """读 entry 文本；解码失败返回 None。"""
    try:
        return zf.read(name).decode("utf-8")
    except (UnicodeDecodeError, KeyError):
        return None


def _scan_secrets_lines(path: str, lines: list[str]) -> Iterator[Violation]:
    for lineno, line in enumerate(lines, start=1):
        for code, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                yield Violation(
                    code=code, severity="error",
                    location=f"{path}:{lineno}",
                    message=f"疑似密钥泄漏（{code}）",
                )


def _scan_secrets_gcp_whole(path: str, text: str) -> Iterator[Violation]:
    """GCP service account：全文同时含 type + private_key 两字段才命中。"""
    if _GCP_SA_TYPE.search(text) and _GCP_SA_PRIVATE_KEY.search(text):
        yield Violation(
            code=L2_SECRET_GCP_SERVICE_ACCOUNT, severity="error",
            location=path,
            message="疑似 GCP service account 凭据 JSON",
        )


def _scan_shell_lines(path: str, lines: list[str]) -> Iterator[Violation]:
    for lineno, line in enumerate(lines, start=1):
        for code, severity, pattern in _SHELL_PATTERNS:
            if pattern.search(line):
                yield Violation(
                    code=code, severity=severity,
                    location=f"{path}:{lineno}",
                    message=f"危险 shell 模式（{code}）",
                )


def _extract_md_fenced_shell(lines: list[str]) -> list[tuple[int, str]]:
    """返回 md 文件内所有 sh/bash/zsh 围栏代码块的行：[(原始行号, 行内容), ...]。"""
    out: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(lines, start=1):
        if not in_fence:
            if _FENCE_OPEN_RE.match(line.strip()):
                in_fence = True
            continue
        # in_fence
        if _FENCE_CLOSE_RE.match(line.strip()):
            in_fence = False
            continue
        out.append((lineno, line))
    return out


def _scan_python_ast(path: str, text: str) -> Iterator[Violation]:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as e:
        yield Violation(
            code=L2_PYTHON_SYNTAX_ERROR, severity="warning",
            location=f"{path}:{e.lineno or 1}",
            message=f"Python 语法错误：{e.msg}",
        )
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "compile"}:
                code = {
                    "eval": L2_PYTHON_EVAL,
                    "exec": L2_PYTHON_EXEC,
                    "compile": L2_PYTHON_COMPILE,
                }[node.func.id]
                yield Violation(
                    code=code, severity="warning",
                    location=f"{path}:{node.lineno}",
                    message=f"调用 {node.func.id}() — 人工确认是否安全",
                )


def run(content: bytes) -> list[Violation]:
    """L2 全部检查。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        # L1 已抓 zip 损坏；L2 静默跳过
        return []

    violations: list[Violation] = []
    with zf:
        for info in zf.infolist():
            if is_macos_metadata(info.filename):
                continue
            if info.is_dir():
                continue
            basename = info.filename.rsplit("/", 1)[-1]
            ext = "." + basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
            if ext not in EXTENSION_WHITELIST:
                continue  # 非白名单文件不扫（L1 已报 extension violation）

            text = _read_text(zf, info.filename)
            if text is None:
                continue
            lines = text.splitlines()

            # 密钥扫描（所有白名单文件逐行）
            violations.extend(_scan_secrets_lines(info.filename, lines))
            # GCP service account 全文模式
            violations.extend(_scan_secrets_gcp_whole(info.filename, text))

            # 危险 shell 模式
            if ext == ".sh":
                violations.extend(_scan_shell_lines(info.filename, lines))
            elif ext == ".md":
                fenced = _extract_md_fenced_shell(lines)
                # 在围栏行上重新跑 _SHELL_PATTERNS（保留原始 lineno）
                for lineno, line in fenced:
                    for code, severity, pattern in _SHELL_PATTERNS:
                        if pattern.search(line):
                            violations.append(Violation(
                                code=code, severity=severity,
                                location=f"{info.filename}:{lineno}",
                                message=f"危险 shell 模式（{code}）— 出现在 markdown 围栏代码块内",
                            ))

            # Python AST
            if ext == ".py":
                violations.extend(_scan_python_ast(info.filename, text))

    return violations
