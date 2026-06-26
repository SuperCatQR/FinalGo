#!/usr/bin/env python3
"""Build static HTML course pages from Jiangsu course Markdown files.

This is intentionally dependency-free so the Phase 1 frontend contract can be
validated in the current repository without introducing a site generator yet.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
COURSES_DIR = ROOT / "docs" / "jiangsu" / "courses"
DEFAULT_OUT_DIR = ROOT / "site" / "courses"
V2_CODES = {"15040", "15043", "15044", "13000", "00023"}
OLD_CODE_TARGETS = {
    "03708": ("15043", "中国近现代史纲要"),
    "03709": ("15044", "马克思主义基本原理"),
}
PUBLIC_AUTO_GEN_CODES = {"15040", "15043", "15044", "13000"}
AUTO_GEN_START_MARKERS = ("<!-- AUTO-GEN-COVERAGE-START", "<!-- AUTO_GEN_START:public-course-coverage")
AUTO_GEN_END_MARKERS = ("<!-- AUTO-GEN-COVERAGE-END", "<!-- AUTO_GEN_END:public-course-coverage")


@dataclass
class CoursePage:
    code: str
    source: Path
    route: str
    title: str
    meta: dict[str, str]
    frontmatter: dict[str, str]
    body: str
    migration_note: bool = False


@dataclass
class BuildResult:
    pages: int = 0
    warnings: list[str] | None = None
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    data: dict[str, str] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and current_key:
            # Preserve nested frontmatter enough for debugging; table metadata is
            # the rendering source of truth for Phase 1.
            data[current_key] = (data[current_key] + " " + line.strip()).strip()
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            data[current_key] = value.strip().strip('"')
    return data, body


def parse_meta_table(body: str) -> dict[str, str]:
    lines = body.splitlines()
    table: dict[str, str] = {}
    for i, line in enumerate(lines):
        if line.strip() == "| 字段 | 内容 |" and i + 1 < len(lines):
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if len(cells) >= 2:
                    table[cells[0]] = cells[1]
                j += 1
            break
    return table


def parse_heading_title(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "课程页"


def canonical_course_sources() -> list[Path]:
    """Return renderable course sources with the 15040 canonical exception."""
    sources: list[Path] = []
    for path in sorted(COURSES_DIR.glob("*.md")):
        code = path.stem
        if code == "index":
            # docs/jiangsu/courses/index.md is the course index source. It is
            # rendered only by render_index(pages), not as /courses/index/.
            continue
        if code == "15040":
            # docs/jiangsu/courses/15040.md is a migration note; the canonical
            # v2 course body is docs/jiangsu/courses/15040/index.md.
            continue
        sources.append(path)
    sources.append(COURSES_DIR / "15040" / "index.md")
    return sorted(sources, key=lambda p: route_for_source(p))


def route_for_source(path: Path) -> str:
    if path.name == "index.md" and path.parent.name == "15040":
        return "/courses/15040/"
    return f"/courses/{path.stem}/"


def code_for_source(path: Path) -> str:
    if path.name == "index.md" and path.parent.name == "15040":
        return "15040"
    return path.stem


def load_course(path: Path) -> CoursePage:
    raw = read_text(path)
    frontmatter, body = split_frontmatter(raw)
    meta = parse_meta_table(body)
    title = parse_heading_title(body)
    code = code_for_source(path)
    return CoursePage(
        code=code,
        source=path,
        route=route_for_source(path),
        title=title,
        meta=meta,
        frontmatter=frontmatter,
        body=body,
        migration_note=(path.name == "15040.md"),
    )


def slug_for_route(route: str) -> Path:
    route = route.strip("/")
    return Path(route) / "index.html" if route else Path("index.html")


def escape_attr(value: str) -> str:
    return html.escape(value, quote=True)


def status_kind(status: str) -> str:
    value = status.strip()
    if value.startswith("🔴"):
        return "red"
    if value.startswith("🟡"):
        return "yellow"
    if value.startswith("🟢"):
        return "green"
    return "red"


def status_banner(page: CoursePage) -> str:
    kind = status_kind(page.meta.get("状态", ""))
    if kind == "yellow":
        return '<div class="status-banner status-banner--yellow">🤖 AI 辅助生成，未经人工校对 — 本页面内容由 AI 辅助生成，可能存在错误。已校对区块见 AI 生成声明表。</div>'
    if kind == "red":
        return '<div class="status-banner status-banner--red">⚠️ 内容建设中 — 本页面为骨架级占位，部分区块内容尚未填充。如需最新信息，请参阅江苏省教育考试院官方公告。</div>'
    return ""


def parse_auto_gen_count(text: str) -> dict[str, int]:
    result = {"normal": 0, "transition": 0, "total": 0}
    patterns = [
        r"<!--\s*AUTO_GEN_COUNT:\s*([^>]+?)\s*-->",
        r"AUTO_GEN_COUNT\s*\|\s*([^|]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        payload = match.group(1)
        for key in result:
            key_match = re.search(rf"{key}\s*=\s*(\d+)", payload)
            if key_match:
                result[key] = int(key_match.group(1))
        if result["total"] == 0 and (result["normal"] or result["transition"]):
            result["total"] = result["normal"] + result["transition"]
        return result
    # Frontmatter fallback for canonical 15040-style YAML.
    fm = re.search(r"auto_gen_count:\s+normal:\s*(\d+)\s+transition:\s*(\d+)\s+total:\s*(\d+)", text, re.S)
    if fm:
        return {"normal": int(fm.group(1)), "transition": int(fm.group(2)), "total": int(fm.group(3))}
    return result


def validate_page(page: CoursePage, result: BuildResult) -> None:
    required = ["省份", "课程代码", "课程名称", "学分", "状态", "版本号", "发布日期", "数据状态", "MIGRATION_STATUS"]
    if page.code in V2_CODES:
        for field in required:
            if not page.meta.get(field):
                result.warnings.append(f"E-R01: {page.source}: 元信息字段缺失：{field}")
        if page.meta.get("MIGRATION_STATUS") != "v2":
            result.warnings.append(f"E-R02: {page.source}: MIGRATION_STATUS 应为 v2")
        if status_kind(page.meta.get("状态", "")) == "red" and not page.meta.get("状态", "").startswith("🔴"):
            result.warnings.append(f"E-R08: {page.source}: 状态无法解析，已按 🔴 降级")
    if page.code in PUBLIC_AUTO_GEN_CODES:
        if not any(marker in page.body for marker in AUTO_GEN_START_MARKERS) or not any(marker in page.body for marker in AUTO_GEN_END_MARKERS):
            result.warnings.append(f"E-R16: {page.source}: 公共课缺少成对 AUTO_GEN marker")
    if page.code == "00023" and not any(marker in page.body for marker in AUTO_GEN_START_MARKERS):
        # Contract: 00023 has no AUTO_GEN and must not warn/error.
        pass


def render_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: render_link(html.unescape(m.group(1)), html.unescape(m.group(2))), escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def normalize_href(href: str) -> str:
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://") or href.startswith("/") or href.startswith("#"):
        return href
    major_match = re.fullmatch(r"(?:\./)?\.\./majors/([^/#?]+)(/)?([#?].*)?", href)
    if major_match:
        suffix = major_match.group(3) or ""
        return f"/majors/{major_match.group(1)}/{suffix}"
    match = re.fullmatch(r"(?:\./|\.\./)?(\d{5})(?:/|\.md)?", href)
    if match:
        return f"/courses/{match.group(1)}/"
    if href.endswith(".md"):
        return href[:-3]
    return href


def render_link(label: str, href: str) -> str:
    href = normalize_href(href)
    external = href.startswith("http://") or href.startswith("https://")
    attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
    cls = ' class="external-link"' if external else ""
    return f'<a href="{escape_attr(href)}"{cls}{attrs}>{html.escape(label)}</a>'


def is_table_start(lines: list[str], i: int) -> bool:
    return i + 1 < len(lines) and lines[i].strip().startswith("|") and re.match(r"^\|?\s*:?-{3,}:?", lines[i + 1].strip()) is not None


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_table(rows: list[str], page: CoursePage | None = None) -> str:
    header = split_row(rows[0])
    body_rows = [split_row(row) for row in rows[2:]]
    classes = ["responsive-table"]
    if header == ["字段", "内容"]:
        classes.append("meta-table")
    parts = [f'<div class="table-scroll"><table class="{" ".join(classes)}">']
    parts.append("<thead><tr>" + "".join(f"<th>{render_inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
    for row in body_rows:
        parts.append("<tr>" + "".join(f"<td>{decorate_cell(render_inline(c), c)}</td>" for c in row) + "</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def decorate_cell(rendered: str, raw: str) -> str:
    raw = raw.strip()
    if raw in {"A", "等级 A"}:
        return '<span class="source-grade source-grade--a">A 官方</span>'
    if raw in {"B", "等级 B"} or raw.startswith("等级 B"):
        return '<span class="source-grade source-grade--b">B 第三方线索</span>'
    if raw in {"C", "等级 C"} or raw.startswith("等级 C"):
        return '<span class="source-grade source-grade--c">C 非官方/待核验</span>'
    if raw == "正常开考":
        return '<span class="state-chip state-chip--normal">正常开考</span>'
    if raw == "停考过渡":
        return '<span class="state-chip state-chip--transition">停考过渡</span>'
    if raw.startswith("🔴"):
        return f'<span class="status-dot status-dot--red"></span>{rendered}'
    if raw.startswith("🟡"):
        return f'<span class="status-dot status-dot--yellow"></span>{rendered}'
    if raw.startswith("🟢"):
        return f'<span class="status-dot status-dot--green"></span>{rendered}'
    if raw in {"待补充", "待统计", "待收集", "待校对"} or "待补充" in raw:
        return f'<span class="placeholder">{rendered}</span>'
    return rendered


def is_auto_gen_meta(text: str) -> bool:
    markers = ("自动生成于", "源数据版本", "生成时间", "以下内容由脚本")
    normalized = text.strip().strip("*_ ")
    return any(marker in normalized for marker in markers)


def render_markdown(body: str, page: CoursePage | None = None) -> str:
    lines = body.splitlines()
    parts: list[str] = []
    in_list = False
    in_auto_gen = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if any(stripped.startswith(marker) for marker in AUTO_GEN_START_MARKERS):
            in_auto_gen = True
            parts.append('<section class="auto-gen" data-readonly="true">')
            i += 1
            continue
        if any(stripped.startswith(marker) for marker in AUTO_GEN_END_MARKERS):
            if in_list:
                parts.append("</ul>")
                in_list = False
            if in_auto_gen:
                parts.append("</section>")
            in_auto_gen = False
            i += 1
            continue
        if stripped.startswith("<!--"):
            i += 1
            continue
        if is_table_start(lines, i):
            if in_list:
                parts.append("</ul>")
                in_list = False
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            parts.append(render_table(rows, page))
            continue
        if stripped.startswith("# "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<h1>{render_inline(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            title = stripped[3:]
            badge = ""
            if "考纲概览" in title or "章节知识树" in title:
                page_status = status_kind(page.meta.get("状态", "")) if page else "red"
                if page_status == "yellow":
                    badge = '<span class="badge badge-ai">🤖 AI 辅助生成</span>'
            if title in {"高频概念表", "题型与答题模板", "真题解析"}:
                badge = '<span class="badge badge-manual">✋ 人工维护</span>'
            parts.append(f"<h2>{render_inline(title)}{badge}</h2>")
        elif stripped.startswith("### "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            title = stripped[4:]
            parts.append(f"<h3>{render_inline(title)}</h3>")
        elif stripped.startswith("#### "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            parts.append(f"<details class=\"knowledge-section\"><summary>{render_inline(stripped[5:])}</summary>")
        elif stripped.startswith("> "):
            if in_list:
                parts.append("</ul>")
                in_list = False
            quote = stripped[2:].strip()
            if in_auto_gen and is_auto_gen_meta(quote):
                parts.append(f'<p class="auto-gen-meta">{render_inline(quote)}</p>')
            elif quote.startswith("📌"):
                parts.append(f'<aside class="manual-note">{render_inline(quote)}</aside>')
            elif quote.startswith("🤖") or "⭐🔧" in quote or "⭐✋" in quote:
                # Machine/manual provenance is represented by badges on headings.
                pass
            else:
                parts.append(f"<blockquote>{render_inline(quote)}</blockquote>")
        elif stripped.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{render_inline(stripped[2:])}</li>")
        elif stripped == "":
            if in_list:
                parts.append("</ul>")
                in_list = False
        else:
            if in_list:
                parts.append("</ul>")
                in_list = False
            # Close details panels before a following top-level paragraph? Keep
            # native HTML forgiving; explicit closing occurs at end below.
            if in_auto_gen and is_auto_gen_meta(stripped):
                parts.append(f'<p class="auto-gen-meta">{render_inline(stripped)}</p>')
            else:
                parts.append(f"<p>{render_inline(stripped)}</p>")
        i += 1
    if in_list:
        parts.append("</ul>")
    # Balance details tags for generated knowledge panels.
    open_details = sum(1 for p in parts if p.startswith("<details"))
    close_details = sum(1 for p in parts if p == "</details>")
    parts.extend("</details>" for _ in range(open_details - close_details))
    return "\n".join(parts)


def render_old_code_page(page: CoursePage) -> str:
    target_code, target_name = OLD_CODE_TARGETS[page.code]
    if page.code == "03708":
        message = "📢 本课程已被替代：自 2024 年 10 月考期起，『中国近现代史纲要』使用新代码 15043。"
    else:
        message = "📢 本课程已被替代：自 2024 年 10 月考期起，『马克思主义基本原理』使用新代码 15044。"
    body = render_markdown(page.body, page)
    banner = f'<div class="jump-banner">{html.escape(message)}<a class="button-link" href="/courses/{target_code}/">查看 {target_code} {html.escape(target_name)}</a></div>'
    return html_shell(page.title, banner + body, canonical=f"/courses/{target_code}/", noindex="noindex, follow")


def render_course_page(page: CoursePage, result: BuildResult) -> str:
    validate_page(page, result)
    body = render_markdown(page.body, page)
    count = parse_auto_gen_count(read_text(page.source))
    count_html = ""
    if page.code in PUBLIC_AUTO_GEN_CODES:
        count_html = f'<p class="auto-gen-count">适用专业统计：正常开考 {count["normal"]} 个，停考过渡 {count["transition"]} 个，合计 {count["total"]} 个。</p>'
    if page.code == "00023" and "AUTO_GEN_START" not in page.body:
        count_html = '<p class="contract-note">本课程无 AUTO_GEN 区域为正常契约，按人工维护/普通静态区块渲染。</p>'
    content = status_banner(page) + count_html + body
    return html_shell(page.title, content, canonical=page.route)


def render_migration_note(page: CoursePage) -> str:
    content = '<div class="migration-note">该文件是迁移说明页，不作为 15040 课程正文渲染。课程正文请访问 <a href="/courses/15040/">/courses/15040/</a>。</div>' + render_markdown(page.body, page)
    return html_shell(page.title, content, canonical="/courses/15040/", noindex="noindex, follow")


def html_shell(title: str, content: str, canonical: str, noindex: str | None = None) -> str:
    robots = f'<meta name="robots" content="{escape_attr(noindex)}">' if noindex else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {robots}
  <link rel="canonical" href="{escape_attr(canonical)}">
  <title>{html.escape(title)} · 江苏自考课程</title>
  <link rel="stylesheet" href="/assets/course.css">
</head>
<body>
  <header class="site-header"><a href="/courses/">江苏自考课程</a></header>
  <main class="course-page">
    <nav class="breadcrumb" aria-label="面包屑"><a href="/">首页</a> &gt; <a href="/courses/">课程</a> &gt; {html.escape(title)}</nav>
    {content}
  </main>
</body>
</html>
"""


def render_index(pages: Iterable[CoursePage]) -> str:
    items = []
    for page in sorted(pages, key=lambda p: p.code):
        label = f"{page.code} {page.meta.get('课程名称') or page.title}"
        tag = '<span class="tag-deprecated">已停用</span>' if page.code in OLD_CODE_TARGETS else ""
        items.append(f'<li><code>{page.code}</code> <a href="{escape_attr(page.route)}">{html.escape(label)}</a> {tag}</li>')
    return html_shell("江苏自考课程页索引", "<h1>江苏自考课程页索引</h1><ul class=\"course-index\">" + "\n".join(items) + "</ul>", canonical="/courses/")


def write_css(out_root: Path) -> None:
    css_dir = out_root / "assets"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "course.css").write_text(CSS, encoding="utf-8")


CSS = """
:root { color-scheme: light; --blue:#1976d2; --red:#e74c3c; --yellow:#f39c12; --green:#27ae60; }
body { margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", Arial, sans-serif; line-height:1.65; color:#263238; background:#f8fafc; }
a { color:var(--blue); text-decoration:none; } a:hover { text-decoration:underline; } a:focus, summary:focus { outline:2px solid var(--blue); outline-offset:2px; }
.site-header { background:#fff; border-bottom:1px solid #e0e0e0; padding:12px 24px; font-weight:700; }
.course-page { max-width:960px; margin:0 auto; padding:24px; background:#fff; min-height:100vh; }
.breadcrumb { color:#607d8b; font-size:.9rem; margin-bottom:16px; }
h1 { font-size:2rem; margin:0 0 16px; } h2 { margin-top:32px; padding-bottom:6px; border-bottom:1px solid #eceff1; } h3 { margin-top:24px; }
.status-banner, .jump-banner, .migration-note, .contract-note, .manual-note { border-radius:8px; padding:12px 16px; margin:16px 0; }
.status-banner--red { background:#fff3cd; border-left:4px solid #ffc107; }
.status-banner--yellow { background:#fff8e1; border-left:4px solid #ff9800; }
.jump-banner { background:#e3f2fd; border:1px solid #2196f3; font-size:1.05rem; }
.migration-note { background:#eceff1; border-left:4px solid #607d8b; }
.contract-note { background:#e8f5e9; border-left:4px solid var(--green); }
.manual-note { background:#e8eaf6; border-left:4px solid #3f51b5; }
.button-link { display:inline-block; margin-left:12px; background:var(--blue); color:#fff; padding:8px 14px; border-radius:6px; font-weight:600; }
.button-link:hover { background:#0d47a1; text-decoration:none; }
.table-scroll { overflow-x:auto; margin:16px 0; }
table { border-collapse:collapse; width:100%; min-width:560px; } th, td { border:1px solid #e0e0e0; padding:8px 10px; vertical-align:top; } th { background:#f5f7fa; text-align:left; } .meta-table th:first-child, .meta-table td:first-child { width:160px; font-weight:600; }
.status-dot { display:inline-block; width:.75em; height:.75em; border-radius:50%; margin-right:.4em; } .status-dot--red{background:var(--red);} .status-dot--yellow{background:var(--yellow);} .status-dot--green{background:var(--green);}
.badge { font-size:.75em; border-radius:4px; padding:2px 6px; margin-left:8px; vertical-align:middle; } .badge-ai{background:#e3f2fd;color:#1565c0;} .badge-manual{background:#fce4ec;color:#c62828;}
.source-grade, .state-chip { display:inline-block; border-radius:3px; padding:1px 6px; font-size:.85em; } .source-grade--a,.state-chip--normal{background:#e8f5e9;color:#1b5e20;} .source-grade--b,.state-chip--transition{background:#fff3e0;color:#e65100;} .source-grade--c{background:#ffebee;color:#b71c1c;}
.placeholder { color:#8a8a8a; border-bottom:1px dashed #bbb; font-style:italic; }
.external-link::after { content:" ↗"; font-size:.75em; }
.auto-gen { border:1px dashed #90caf9; padding:12px; border-radius:8px; background:#fbfdff; } .auto-gen-meta { display:none; } .auto-gen-count { color:#455a64; background:#f5f8ff; padding:8px 12px; border-radius:6px; }
details { margin:8px 0; } summary { cursor:pointer; padding:8px 12px; border-left:3px solid transparent; } details[open] > summary { background:#f5f8ff; border-left-color:#2196f3; }
.course-index li { margin:8px 0; } .tag-deprecated { color:#777; background:#eee; border-radius:3px; padding:1px 5px; font-size:.8em; }
@media (max-width: 767px) { .course-page{padding:16px;} h1{font-size:1.5rem;} table{font-size:.9rem;} .button-link{display:block;margin:10px 0 0;} }
@media print { body{background:#fff;} .site-header,.status-banner,.badge,.jump-banner,.auto-gen-meta{display:none!important;} .course-page{max-width:none;padding:0;} a{color:#000;text-decoration:none;} tr, table { page-break-inside: avoid; } .breadcrumb{color:#000;} }
""".strip() + "\n"


def build(out_dir: Path) -> BuildResult:
    result = BuildResult()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_css(out_dir.parent)

    pages = [load_course(path) for path in canonical_course_sources()]
    for page in pages:
        if page.code in OLD_CODE_TARGETS:
            html_text = render_old_code_page(page)
        else:
            html_text = render_course_page(page, result)
        target = out_dir.parent / slug_for_route(page.route)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
        result.pages += 1

    # Emit 15040.md as a noindex migration note to avoid treating it as body.
    migration_page = load_course(COURSES_DIR / "15040.md")
    migration_target = out_dir.parent / "courses" / "15040-migration" / "index.html"
    migration_target.parent.mkdir(parents=True, exist_ok=True)
    migration_target.write_text(render_migration_note(migration_page), encoding="utf-8")
    result.pages += 1

    index_target = out_dir.parent / "courses" / "index.html"
    index_target.parent.mkdir(parents=True, exist_ok=True)
    index_target.write_text(render_index(pages), encoding="utf-8")
    result.pages += 1

    report = ["# Course frontend build report", "", f"Pages generated: {result.pages}", ""]
    if result.warnings:
        report.append("## Warnings")
        report.extend(f"- {w}" for w in result.warnings)
    else:
        report.append("No warnings.")
    if result.errors:
        report.append("## Errors")
        report.extend(f"- {e}" for e in result.errors)
    (out_dir.parent / "course-build-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static course HTML pages")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for /courses pages")
    args = parser.parse_args()
    result = build(Path(args.out_dir))
    print(f"Generated {result.pages} pages")
    if result.warnings:
        print(f"Warnings: {len(result.warnings)}")
        for warning in result.warnings:
            print(f"[WARN] {warning}")
    if result.errors:
        print(f"Errors: {len(result.errors)}")
        for error in result.errors:
            print(f"[ERR] {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
