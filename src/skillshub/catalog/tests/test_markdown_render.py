"""readme markdown 渲染测试 (含 XSS 防御)。"""
from skillshub.catalog.markdown_render import render_readme


def test_render_basic_markdown():
    md = "# Title\n\n**bold** _italic_\n\n- a\n- b\n"
    html = render_readme(md)
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<ul>" in html
    assert "<li>a</li>" in html


def test_render_strips_script_tag():
    md = "正常段\n\n<script>alert('xss')</script>\n\n继续"
    html = render_readme(md)
    # bleach strip=True 去掉标签本身, 内容以纯文本留下 (不可执行)
    assert "<script>" not in html
    assert "</script>" not in html
    assert "正常段" in html
    assert "继续" in html


def test_render_strips_javascript_href():
    md = '[click](javascript:alert(1))'
    html = render_readme(md)
    assert "javascript:" not in html
    # bleach 会把不允许的 href scheme 整个 strip 或保留链接但去 href
    assert "alert(1)" not in html


def test_render_strips_img_onerror():
    md = '<img src="x.png" onerror="alert(1)">'
    html = render_readme(md)
    assert "onerror" not in html
    assert "alert(1)" not in html
    # src 应保留
    assert 'src="x.png"' in html or "src=x.png" in html


def test_render_preserves_table():
    md = """| col1 | col2 |
| --- | --- |
| a | b |
"""
    html = render_readme(md)
    assert "<table>" in html
    assert "<thead>" in html
    assert "<td>a</td>" in html
