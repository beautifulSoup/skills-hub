"""L2 检查单元测试。"""
from __future__ import annotations

import io
import zipfile

from skillshub.submit.machine_review import l2
from skillshub.submit.machine_review.violations import (
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
)


VALID_FM = b"---\nname: my-skill\ndescription: x\n---\nbody"


def make_zip(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    return buf.getvalue()


# ─── 密钥正则 ───
def test_l2_secret_aws_access_key_hit():
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/config.py": "key = 'AKIAIOSFODNN7EXAMPLE'\n",
    })
    v = l2.run(content)
    hits = [x for x in v if x.code == L2_SECRET_AWS_ACCESS_KEY]
    assert hits
    assert hits[0].severity == "error"
    assert "config.py:1" in hits[0].location


def test_l2_secret_aws_secret_key_hit():
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/config.py": "aws_secret_access_key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'\n",
    })
    v = l2.run(content)
    assert [x for x in v if x.code == L2_SECRET_AWS_SECRET_KEY]


def test_l2_secret_gcp_service_account_hit():
    gcp = '{"type": "service_account", "private_key": "-----BEGIN..."}'
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/sa.json": gcp})
    v = l2.run(content)
    assert [x for x in v if x.code == L2_SECRET_GCP_SERVICE_ACCOUNT]


def test_l2_secret_openai_key_hit():
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/c.py": "OPENAI_KEY = 'sk-proj-abcdefghijklmnopqrstuvwxyz1234'\n",
    })
    v = l2.run(content)
    assert [x for x in v if x.code == L2_SECRET_OPENAI_API_KEY]


def test_l2_secret_anthropic_key_hit():
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/c.py": "K = 'sk-ant-abcdefghijklmnopqrstuvwxyz12'\n",
    })
    v = l2.run(content)
    assert [x for x in v if x.code == L2_SECRET_ANTHROPIC_API_KEY]


def test_l2_secret_github_pat_hit():
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/c.py": "T = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'\n",
    })
    v = l2.run(content)
    assert [x for x in v if x.code == L2_SECRET_GITHUB_PAT]


def test_l2_secret_github_fine_grained_hit():
    token = "github_pat_" + "A" * 82
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/c.py": f"T = '{token}'\n",
    })
    v = l2.run(content)
    assert [x for x in v if x.code == L2_SECRET_GITHUB_FINE_GRAINED]


def test_l2_secret_ssh_private_key_hit():
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/key.txt": "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n",
    })
    v = l2.run(content)
    assert [x for x in v if x.code == L2_SECRET_SSH_PRIVATE_KEY]


def test_l2_secret_no_false_positive():
    """普通字符串不应触发任何密钥模式。"""
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/c.py": "name = 'hello world'\nemail = 'a@b.c'\n",
    })
    v = l2.run(content)
    assert not [x for x in v if x.code.startswith("l2.secret.")]


# ─── 危险 shell ───
def test_l2_shell_rm_rf_root_hit():
    sh = b"#!/bin/sh\nrm -rf /\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/install.sh": sh})
    v = l2.run(content)
    hits = [x for x in v if x.code == L2_DANGEROUS_SHELL_RM_RF_ROOT]
    assert hits
    assert hits[0].severity == "error"


def test_l2_shell_rm_rf_subpath_no_hit():
    """rm -rf /tmp/foo 不命中（路径非根）。"""
    sh = b"#!/bin/sh\nrm -rf /tmp/foo\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/install.sh": sh})
    v = l2.run(content)
    assert not [x for x in v if x.code == L2_DANGEROUS_SHELL_RM_RF_ROOT]


def test_l2_shell_curl_pipe_sh_hit():
    sh = b"#!/bin/sh\ncurl https://example.com/x | sh\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/install.sh": sh})
    v = l2.run(content)
    hits = [x for x in v if x.code == L2_DANGEROUS_SHELL_CURL_PIPE_SH]
    assert hits
    assert hits[0].severity == "warning"


def test_l2_shell_base64_pipe_sh_hit():
    sh = b"#!/bin/sh\necho 'foo' | base64 -d | bash\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/install.sh": sh})
    v = l2.run(content)
    assert [x for x in v if x.code == L2_DANGEROUS_SHELL_BASE64_PIPE_SH]


def test_l2_shell_eval_hit():
    sh = b'#!/bin/sh\neval "$user_input"\n'
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/install.sh": sh})
    v = l2.run(content)
    assert [x for x in v if x.code == L2_DANGEROUS_SHELL_EVAL]


# ─── markdown 围栏 ───
def test_l2_md_fenced_block_scanned():
    """围栏内的 rm -rf / 命中。"""
    md = "# Title\n\n```bash\nrm -rf /\n```\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/install.md": md})
    v = l2.run(content)
    assert [x for x in v if x.code == L2_DANGEROUS_SHELL_RM_RF_ROOT]


def test_l2_md_prose_not_scanned():
    """正文文字含 rm -rf / 字面但非围栏，不命中。"""
    md = "# Title\n\n注意：千万不要执行 rm -rf / 这样的命令。\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/install.md": md})
    v = l2.run(content)
    assert not [x for x in v if x.code == L2_DANGEROUS_SHELL_RM_RF_ROOT]


def test_l2_md_python_fence_not_scanned_for_shell():
    """python 围栏内的 rm -rf / 不应被扫（仅 sh/bash/zsh 围栏）。"""
    md = "# Title\n\n```python\n# 文档示例\n# rm -rf / 这是注释\n```\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/x.md": md})
    v = l2.run(content)
    assert not [x for x in v if x.code.startswith("l2.dangerous_shell.")]


# ─── Python AST ───
def test_l2_python_eval_hit():
    py = "x = 1\nresult = eval('2+2')\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/run.py": py})
    v = l2.run(content)
    hits = [x for x in v if x.code == L2_PYTHON_EVAL]
    assert hits
    assert hits[0].severity == "warning"
    assert "run.py:2" in hits[0].location


def test_l2_python_exec_hit():
    py = "exec('print(1)')\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/run.py": py})
    v = l2.run(content)
    assert [x for x in v if x.code == L2_PYTHON_EXEC]


def test_l2_python_compile_hit():
    py = "compile('1+2', '<s>', 'eval')\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/run.py": py})
    v = l2.run(content)
    assert [x for x in v if x.code == L2_PYTHON_COMPILE]


def test_l2_python_getattr_obfuscation_known_miss():
    """getattr(__builtins__, 'eval')(x) 不命中（设计：MVP 仅扫 ast.Name 裸调）。"""
    py = "x = getattr(__builtins__, 'eval')('1')\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/run.py": py})
    v = l2.run(content)
    assert not [x for x in v if x.code in {L2_PYTHON_EVAL, L2_PYTHON_EXEC, L2_PYTHON_COMPILE}]


def test_l2_python_syntax_error_caught():
    py = "def broken(\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/broken.py": py})
    v = l2.run(content)
    assert [x for x in v if x.code == L2_PYTHON_SYNTAX_ERROR]


def test_l2_python_lambda_eval_method_no_hit():
    """obj.eval() 方法调用不命中（不是 ast.Name）。"""
    py = "obj.eval('1+2')\n"
    content = make_zip({"myskill/SKILL.md": VALID_FM, "myskill/run.py": py})
    v = l2.run(content)
    assert not [x for x in v if x.code == L2_PYTHON_EVAL]


# ─── 跨文件类型不漏不重 ───
def test_l2_skips_non_whitelist_extension():
    """非白名单后缀文件不扫密钥（L1 已报 extension violation）。"""
    content = make_zip({
        "myskill/SKILL.md": VALID_FM,
        "myskill/secret.exe": "AKIAIOSFODNN7EXAMPLE",
    })
    v = l2.run(content)
    assert not [x for x in v if x.code == L2_SECRET_AWS_ACCESS_KEY]
