"""UA 猜 OS (T10)：用于详情页 OS picker 默认值。

规则（按优先级）：
  含 "Mac OS X" 或 "Macintosh" → macos
  含 "Windows NT"              → windows
  其它 (含 Linux / Android / 空) → linux
"""
from typing import Literal

OsLiteral = Literal["linux", "macos", "windows"]


def guess_os(ua: str) -> OsLiteral:
    if not ua:
        return "linux"
    if "Mac OS X" in ua or "Macintosh" in ua:
        return "macos"
    if "Windows NT" in ua:
        return "windows"
    return "linux"
