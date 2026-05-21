"""Readme markdown 渲染 + bleach 白名单清洗 (服务端 XSS 防御)。

D3: python-markdown 转 HTML (含 fenced_code + tables 扩展);
    bleach 按白名单清洗,危险标签/属性 strip。
"""
import bleach
import markdown

ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "ul", "ol", "li",
    "strong", "em", "blockquote",
    "code", "pre",
    "a", "img",
    "table", "thead", "tbody", "tr", "td", "th",
]

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "img": ["src", "alt", "title"],
    "code": ["class"],  # 给二期代码高亮留口子
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def render_readme(text: str) -> str:
    """转 markdown → bleach 清洗 → 安全 HTML。

    Args:
        text: 原始 markdown 文本

    Returns:
        清洗后的 HTML 字符串 (可在模板用 |safe 渲染)
    """
    if not text:
        return ""

    html = markdown.markdown(
        text,
        extensions=["fenced_code", "tables"],
        output_format="html",
    )
    cleaned = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return cleaned
