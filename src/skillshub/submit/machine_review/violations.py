"""Violation dataclass + 全部 code 常量。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    code: str
    severity: str       # "error" | "warning" | "info"
    location: str
    message: str

    def asdict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "location": self.location,
            "message": self.message,
        }


# ── L1 codes ─────────────────────────────────────────────
L1_ZIP_STRUCTURE = "l1.zip_structure"
L1_SKILL_MD_FRONTMATTER = "l1.skill_md_frontmatter"
L1_NAME_FORMAT = "l1.name_format"
L1_NAME_COLLISION = "l1.name_collision"
L1_SIZE_LIMIT = "l1.size_limit"
L1_EXTENSION_WHITELIST = "l1.extension_whitelist"
L1_INTERNAL_ERROR = "l1.internal_error"

# ── L2 codes ─────────────────────────────────────────────
L2_SECRET_AWS_ACCESS_KEY = "l2.secret.aws_access_key"
L2_SECRET_AWS_SECRET_KEY = "l2.secret.aws_secret_key"
L2_SECRET_GCP_SERVICE_ACCOUNT = "l2.secret.gcp_service_account"
L2_SECRET_OPENAI_API_KEY = "l2.secret.openai_api_key"
L2_SECRET_ANTHROPIC_API_KEY = "l2.secret.anthropic_api_key"
L2_SECRET_GITHUB_PAT = "l2.secret.github_pat"
L2_SECRET_GITHUB_FINE_GRAINED = "l2.secret.github_fine_grained"
L2_SECRET_SSH_PRIVATE_KEY = "l2.secret.ssh_private_key"
L2_DANGEROUS_SHELL_RM_RF_ROOT = "l2.dangerous_shell.rm_rf_root"
L2_DANGEROUS_SHELL_CURL_PIPE_SH = "l2.dangerous_shell.curl_pipe_sh"
L2_DANGEROUS_SHELL_BASE64_PIPE_SH = "l2.dangerous_shell.base64_pipe_sh"
L2_DANGEROUS_SHELL_EVAL = "l2.dangerous_shell.eval"
L2_PYTHON_EVAL = "l2.python.eval"
L2_PYTHON_EXEC = "l2.python.exec"
L2_PYTHON_COMPILE = "l2.python.compile"
L2_PYTHON_SYNTAX_ERROR = "l2.python.syntax_error"

# 引擎版本（写入 machine_review_result.engine_version）
ENGINE_VERSION = "1.0"

# 文件大小上限
MAX_FILE_SIZE = 5 * 1024 * 1024   # 5 MB
MAX_TOTAL_SIZE = 20 * 1024 * 1024 # 20 MB

# 后缀白名单
EXTENSION_WHITELIST = {
    ".md", ".py", ".js", ".ts", ".json",
    ".yaml", ".yml", ".txt", ".sh", ".toml",
}

# macOS 元数据前缀（解压时跳过）
MACOS_METADATA_PREFIX = "__MACOSX/"
MACOS_METADATA_BASENAMES = {".DS_Store"}


def is_macos_metadata(name: str) -> bool:
    """L1 / L2 共享：判断 zip entry 是否为 macOS 元数据，扫描时跳过。"""
    if name.startswith(MACOS_METADATA_PREFIX):
        return True
    basename = name.rstrip("/").rsplit("/", 1)[-1]
    return basename in MACOS_METADATA_BASENAMES
