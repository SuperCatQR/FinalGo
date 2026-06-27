#!/usr/bin/env python3
"""Build static HTML course pages from Jiangsu course Markdown files.

This is intentionally dependency-free so the Phase 1 frontend contract can be
validated in the current repository without introducing a site generator yet.
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
COURSES_DIR = ROOT / "docs" / "jiangsu" / "courses"
MAJORS_DIR = ROOT / "docs" / "jiangsu" / "majors"
SITE_INDEX_SOURCE = ROOT / "docs" / "jiangsu" / "index.md"
DEFAULT_OUT_DIR = ROOT / "site" / "courses"
# Home sections that are candidate-facing; internal R&D notes are dropped (IA-1).
HOME_KEEP_SECTIONS = {"当前口径", "核心数字", "内容入口", "官方来源"}
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


@dataclass
class RenderContext:
    """Per-page render state used for dead-link resolution (IA-5).

    base_route is the absolute route of the page being rendered (e.g.
    "/majors/030101K-law/"); relative links in the source are resolved
    against it, then checked against allowed_routes. Anything not produced
    this slice is degraded to non-link text instead of emitting a dead <a>.
    """

    base_route: str = "/"
    allowed_routes: set[str] = field(default_factory=set)
    stub_slugs: set[str] = field(default_factory=set)
    is_majors_index: bool = False
    source_dir: Path | None = None
    source_label: str = "?"
    warnings: list[str] | None = None


# Single-threaded build; render functions read this while emitting a page.
CTX = RenderContext()


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


def output_route_for_source(target: Path) -> str | None:
    """Map a resolved source-tree path to the canonical output route, or None.

    Relative links in Markdown are relative to the *source* file location
    (docs tree), not the output route — so we resolve against the source dir
    and translate, rather than path-joining output routes (which would mis-
    resolve `../majors/x` from a deeper output dir).
    """
    name = target.name
    # /courses/ index
    if target == COURSES_DIR or (name == "index.md" and target.parent == COURSES_DIR):
        return "/courses/"
    # /courses/<code>/ from <code>.md, bare <code>/ dir, or <code>/index.md
    if target.parent == COURSES_DIR and target.suffix == ".md" and re.fullmatch(r"\d{5}", target.stem):
        return f"/courses/{target.stem}/"
    if target.parent == COURSES_DIR and re.fullmatch(r"\d{5}", name):
        return f"/courses/{name}/"
    if name == "index.md" and target.parent.parent == COURSES_DIR and re.fullmatch(r"\d{5}", target.parent.name):
        return f"/courses/{target.parent.name}/"
    # /majors/ index
    if target == MAJORS_DIR or (name == "index.md" and target.parent == MAJORS_DIR):
        return "/majors/"
    # /majors/<slug>/ from bare dir, <slug>.md, or <slug>/index.md
    if target.parent == MAJORS_DIR and target.suffix == "":
        return f"/majors/{name}/"
    if target.parent == MAJORS_DIR and target.suffix == ".md":
        return f"/majors/{target.stem}/"
    if name == "index.md" and target.parent.parent == MAJORS_DIR:
        return f"/majors/{target.parent.name}/"
    # site home
    if target == SITE_INDEX_SOURCE:
        return "/"
    return None


def normalize_absolute_route(path: str) -> str:
    m = re.fullmatch(r"/courses/(\d{5})(?:\.md|/)?", path)
    if m:
        return f"/courses/{m.group(1)}/"
    m = re.fullmatch(r"/majors/([^/]+?)(?:\.md|/)?", path)
    if m:
        return f"/majors/{m.group(1)}/"
    if path.endswith(".md"):
        return path[:-3]
    return path


def resolve_internal_route(href: str) -> str | None:
    """Return the canonical output route for an internal link, or None if it
    maps to nothing this slice produces (caller degrades to non-link text)."""
    path = href.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return None
    if path.startswith("/"):
        return normalize_absolute_route(path)
    base = getattr(CTX, "source_dir", None) or COURSES_DIR
    try:
        target = (base / path).resolve()
    except (OSError, RuntimeError):
        return None
    return output_route_for_source(target)


def render_link(label: str, href: str) -> str:
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://"):
        return f'<a href="{escape_attr(href)}" class="external-link" target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'
    if href.startswith("#"):
        return f'<a href="{escape_attr(href)}">{html.escape(label)}</a>'
    fragment = ""
    if "#" in href:
        fragment = "#" + href.split("#", 1)[1]
    route = resolve_internal_route(href)
    # No whitelist configured (e.g. standalone use) → keep canonical route.
    if route is not None and (not CTX.allowed_routes or route in CTX.allowed_routes):
        return f'<a href="{escape_attr(route + fragment)}">{html.escape(label)}</a>'
    # Dead-link policy (IA-5): degrade to non-link text + build warning.
    if CTX.warnings is not None:
        CTX.warnings.append(f"E-L01: 站内链接目标未产出，已降级为文本：{href} (源 {getattr(CTX, 'source_label', '?')})")
    return f'<span class="dead-link" title="该入口本期未产出独立页面">{html.escape(label)}</span>'


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
    # IA-2 majors index: flag stub majors with a 建设中 chip on the 页面 cell.
    page_col = header.index("页面") if (CTX.is_majors_index and "页面" in header) else -1
    parts = [f'<div class="table-scroll"><table class="{" ".join(classes)}">']
    parts.append("<thead><tr>" + "".join(f"<th>{render_inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
    for row in body_rows:
        cells = []
        for idx, c in enumerate(row):
            cell = decorate_cell(render_inline(c), c)
            if idx == page_col:
                m = re.search(r"\(([^)]+)\)", c)
                slug = posixpath.basename(m.group(1).rstrip("/")) if m else ""
                if slug in CTX.stub_slugs:
                    cell += ' <span class="state-chip state-chip--transition">建设中</span>'
            cells.append(f"<td>{cell}</td>")
        parts.append("<tr>" + "".join(cells) + "</tr>")
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


def course_crumb(title: str) -> str:
    return breadcrumb([("/", "首页"), ("/courses/", "课程"), (None, title)])


def render_old_code_page(page: CoursePage) -> str:
    CTX.source_dir = page.source.parent
    CTX.source_label = str(page.source.relative_to(ROOT))
    target_code, target_name = OLD_CODE_TARGETS[page.code]
    if page.code == "03708":
        message = "📢 本课程已被替代：自 2024 年 10 月考期起，『中国近现代史纲要』使用新代码 15043。"
    else:
        message = "📢 本课程已被替代：自 2024 年 10 月考期起，『马克思主义基本原理』使用新代码 15044。"
    body = render_markdown(page.body, page)
    banner = f'<div class="jump-banner">{html.escape(message)}<a class="button-link" href="/courses/{target_code}/">查看 {target_code} {html.escape(target_name)}</a></div>'
    return html_shell(page.title, banner + body, canonical=f"/courses/{target_code}/",
                      nav_active="courses", crumb=course_crumb(page.title), noindex="noindex, follow")


def render_course_page(page: CoursePage, result: BuildResult) -> str:
    CTX.source_dir = page.source.parent
    CTX.source_label = str(page.source.relative_to(ROOT))
    validate_page(page, result)
    body = render_markdown(page.body, page)
    count = parse_auto_gen_count(read_text(page.source))
    count_html = ""
    if page.code in PUBLIC_AUTO_GEN_CODES:
        count_html = f'<p class="auto-gen-count">适用专业统计：正常开考 {count["normal"]} 个，停考过渡 {count["transition"]} 个，合计 {count["total"]} 个。</p>'
    if page.code == "00023" and "AUTO_GEN_START" not in page.body:
        count_html = '<p class="contract-note">本课程无 AUTO_GEN 区域为正常契约，按人工维护/普通静态区块渲染。</p>'
    content = status_banner(page) + count_html + body
    return html_shell(page.title, content, canonical=page.route,
                      nav_active="courses", crumb=course_crumb(page.title))


def render_migration_note(page: CoursePage) -> str:
    CTX.source_dir = page.source.parent
    CTX.source_label = str(page.source.relative_to(ROOT))
    content = '<div class="migration-note">该文件是迁移说明页，不作为 15040 课程正文渲染。课程正文请访问 <a href="/courses/15040/">/courses/15040/</a>。</div>' + render_markdown(page.body, page)
    return html_shell(page.title, content, canonical="/courses/15040/",
                      nav_active="courses", crumb=course_crumb(page.title), noindex="noindex, follow")


SITE_FOOTER = (
    '<footer class="site-footer">'
    '<p class="footer-priority">数据源优先级：江苏省教育考试院官方公告与附件 &gt; 主考学校转发公告 &gt; 后续人工校对资料。</p>'
    '<p class="footer-note">本站为江苏自考资料参考，口径以江苏省教育考试院官方公告为准。</p>'
    '</footer>'
)


def site_nav(active: str) -> str:
    links = [("/", "首页", "home"), ("/majors/", "专业", "majors"), ("/courses/", "课程", "courses")]
    items = []
    for href, label, key in links:
        cls = ' aria-current="page"' if key == active else ""
        items.append(f'<a href="{href}"{cls}>{label}</a>')
    return (
        '<header class="site-header">'
        '<a class="site-brand" href="/">江苏自考资料库</a>'
        f'<nav class="site-nav" aria-label="主导航">{"".join(items)}</nav>'
        '</header>'
    )


def breadcrumb(trail: list[tuple[str | None, str]]) -> str:
    """trail = [(href|None, label), ...]; last item is current (no link)."""
    parts = []
    for href, label in trail:
        if href:
            parts.append(f'<a href="{href}">{html.escape(label)}</a>')
        else:
            parts.append(f'<span aria-current="page">{html.escape(label)}</span>')
    return '<nav class="breadcrumb" aria-label="面包屑">' + " &gt; ".join(parts) + "</nav>"


def html_shell(title: str, content: str, canonical: str, *, nav_active: str = "courses",
               crumb: str = "", noindex: str | None = None) -> str:
    robots = f'<meta name="robots" content="{escape_attr(noindex)}">' if noindex else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {robots}
  <link rel="canonical" href="{escape_attr(canonical)}">
  <title>{html.escape(title)} · 江苏自考资料库</title>
  <link rel="stylesheet" href="/assets/course.css">
</head>
<body>
  {site_nav(nav_active)}
  <main class="course-page">
    {crumb}
    {content}
  </main>
  {SITE_FOOTER}
</body>
</html>
"""


def render_index(pages: Iterable[CoursePage]) -> str:
    items = []
    for page in sorted(pages, key=lambda p: p.code):
        label = f"{page.code} {page.meta.get('课程名称') or page.title}"
        tag = '<span class="tag-deprecated">已停用</span>' if page.code in OLD_CODE_TARGETS else ""
        items.append(f'<li><code>{page.code}</code> <a href="{escape_attr(page.route)}">{html.escape(label)}</a> {tag}</li>')
    content = "<h1>江苏自考课程页索引</h1><ul class=\"course-index\">" + "\n".join(items) + "</ul>"
    return html_shell("江苏自考课程页索引", content, canonical="/courses/",
                      nav_active="courses", crumb=breadcrumb([("/", "首页"), (None, "课程")]))


def split_sections(body: str) -> list[tuple[str, list[str]]]:
    """Split a Markdown body into (section-title, lines) by `## ` headings.
    Lines before the first `## ` are returned under the "" key (preamble)."""
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            sections.append((current_title, current_lines))
            current_title = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    sections.append((current_title, current_lines))
    return sections


def render_home() -> str:
    """IA-1 site home: render docs/jiangsu/index.md, keeping only the
    candidate-facing sections (review building 5 / OQ-1). Internal R&D notes
    (目录组织原则 / PDF 处理状态 / 建议页面结构 / 待补全) are dropped."""
    CTX.source_dir = SITE_INDEX_SOURCE.parent
    CTX.source_label = str(SITE_INDEX_SOURCE.relative_to(ROOT))
    raw = read_text(SITE_INDEX_SOURCE)
    _, body = split_frontmatter(raw)
    kept_lines: list[str] = []
    for title, lines in split_sections(body):
        if title == "" or title in HOME_KEEP_SECTIONS:
            kept_lines.extend(lines)
    content = render_markdown("\n".join(kept_lines))
    return html_shell("江苏自考资料库", content, canonical="/", nav_active="home")


MAJOR_REQUIRED_META = ["专业代码", "专业名称", "层次"]


def is_stub_major(body: str) -> bool:
    """A major page is a stub unless it carries real policy content.
    Real majors have `## 政策状态`; stubs carry `## 处理产物` (internal
    artifact paths) and/or `## 待校对`. Real: 4/54 (law/050101/080901/120203K)."""
    return "## 政策状态" not in body or "## 处理产物" in body


def major_meta_table(meta: dict[str, str]) -> str:
    rows = []
    for key in ["专业代码", "专业名称", "层次", "省份"]:
        val = meta.get(key)
        if val:
            rows.append(f"<tr><td>{html.escape(key)}</td><td>{html.escape(val)}</td></tr>")
    return (
        '<div class="table-scroll"><table class="responsive-table meta-table">'
        '<thead><tr><th>字段</th><th>内容</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div>"
    )


def major_crumb(title: str) -> str:
    return breadcrumb([("/", "首页"), ("/majors/", "专业"), (None, title)])


def render_major_page(slug: str, source: Path, result: BuildResult) -> str:
    raw = read_text(source)
    _, body = split_frontmatter(raw)
    meta = parse_meta_table(body)
    title = parse_heading_title(body)
    route = f"/majors/{slug}/"
    CTX.source_dir = source.parent
    CTX.source_label = str(source.relative_to(ROOT))
    for key in MAJOR_REQUIRED_META:
        if not meta.get(key):
            result.warnings.append(f"E-M01: {CTX.source_label}: 专业元信息缺失：{key}")
    if is_stub_major(body):
        # Stub: render placeholder only. Never render `## 处理产物` /
        # sources/plan.raw.* internal paths to candidates (blocker 1).
        banner = (
            '<div class="status-banner status-banner--red">⚠️ 内容校对中 — '
            '该专业页正在建设，口径以江苏省教育考试院官方公告为准。</div>'
        )
        content = f"<h1>{html.escape(title)}</h1>{banner}{major_meta_table(meta)}"
    else:
        content = render_markdown(body)
    return html_shell(title, content, canonical=route, nav_active="majors", crumb=major_crumb(title))


def render_majors_index(stub_slugs: set[str]) -> str:
    """IA-2: render the existing docs/jiangsu/majors/index.md directly (review
    building 4 — single source, no synthesis drift). Stub majors get a 建设中
    chip via the render-table hook."""
    source = MAJORS_DIR / "index.md"
    CTX.source_dir = source.parent
    CTX.source_label = str(source.relative_to(ROOT))
    CTX.is_majors_index = True
    CTX.stub_slugs = stub_slugs
    _, body = split_frontmatter(read_text(source))
    content = render_markdown(body)
    CTX.is_majors_index = False
    return html_shell("江苏自考专业索引", content, canonical="/majors/",
                      nav_active="majors", crumb=breadcrumb([("/", "首页"), (None, "专业")]))


def write_css(out_root: Path) -> None:
    css_dir = out_root / "assets"
    css_dir.mkdir(parents=True, exist_ok=True)
    (css_dir / "course.css").write_text(CSS, encoding="utf-8")


CSS = """
:root {
  color-scheme: light;
  --blue:#1565c0; --red:#c62828; --yellow:#f39c12; --green:#2e7d32;
  --ink:#1f2933; --ink-soft:#52606d; --line:#e0e0e0; --bg:#f8fafc; --surface:#fff;
  --fs-1:.8rem; --fs-2:.9rem; --fs-3:1rem; --fs-4:1.25rem; --fs-5:1.5rem; --fs-6:2rem;
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px;
  --radius:8px; --maxw:960px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", Arial, sans-serif;
}
body { margin:0; font-family:var(--font); line-height:1.65; color:var(--ink); background:var(--bg); display:flex; flex-direction:column; min-height:100vh; }
a { color:var(--blue); text-decoration:none; } a:hover { text-decoration:underline; } a:focus, summary:focus, .site-nav a:focus { outline:2px solid var(--blue); outline-offset:2px; }
.site-header { display:flex; align-items:center; gap:var(--sp-5); flex-wrap:wrap; background:var(--surface); border-bottom:1px solid var(--line); padding:var(--sp-3) var(--sp-5); }
.site-brand { font-weight:700; font-size:var(--fs-4); color:var(--ink); }
.site-nav { display:flex; gap:var(--sp-4); } .site-nav a { color:var(--ink-soft); font-weight:600; padding:var(--sp-1) 0; border-bottom:2px solid transparent; }
.site-nav a:hover { color:var(--blue); text-decoration:none; } .site-nav a[aria-current="page"] { color:var(--blue); border-bottom-color:var(--blue); }
.course-page { width:100%; max-width:var(--maxw); margin:0 auto; padding:var(--sp-5); background:var(--surface); flex:1 0 auto; box-sizing:border-box; }
.breadcrumb { color:var(--ink-soft); font-size:var(--fs-2); margin-bottom:var(--sp-4); } .breadcrumb span[aria-current="page"] { color:var(--ink); }
.site-footer { flex-shrink:0; background:#eceff1; border-top:1px solid var(--line); color:var(--ink-soft); font-size:var(--fs-2); padding:var(--sp-4) var(--sp-5); }
.site-footer p { margin:var(--sp-1) 0; } .footer-priority { font-weight:600; }
h1 { font-size:var(--fs-6); margin:0 0 var(--sp-4); } h2 { font-size:var(--fs-5); margin-top:var(--sp-6); padding-bottom:var(--sp-1); border-bottom:1px solid #eceff1; } h3 { font-size:var(--fs-4); margin-top:var(--sp-5); }
.status-banner, .jump-banner, .migration-note, .contract-note, .manual-note { border-radius:var(--radius); padding:var(--sp-3) var(--sp-4); margin:var(--sp-4) 0; }
.status-banner--red { background:#fff8e1; border-left:4px solid #b26a00; color:#5a3d00; }
.status-banner--yellow { background:#fff8e1; border-left:4px solid #b26a00; color:#5a3d00; }
.jump-banner { background:#e3f2fd; border:1px solid #2196f3; font-size:1.05rem; }
.migration-note { background:#eceff1; border-left:4px solid #607d8b; }
.contract-note { background:#e8f5e9; border-left:4px solid var(--green); }
.manual-note { background:#e8eaf6; border-left:4px solid #3f51b5; }
.button-link { display:inline-block; margin-left:var(--sp-3); background:var(--blue); color:#fff; padding:var(--sp-2) 14px; border-radius:6px; font-weight:600; }
.button-link:hover { background:#0d47a1; text-decoration:none; }
.table-scroll { overflow-x:auto; margin:var(--sp-4) 0; }
table { border-collapse:collapse; width:100%; min-width:560px; } th, td { border:1px solid var(--line); padding:var(--sp-2) 10px; vertical-align:top; } th { background:#f5f7fa; text-align:left; } .meta-table th:first-child, .meta-table td:first-child { width:160px; font-weight:600; }
.status-dot { display:inline-block; width:.75em; height:.75em; border-radius:50%; margin-right:.4em; } .status-dot--red{background:var(--red);} .status-dot--yellow{background:var(--yellow);} .status-dot--green{background:var(--green);}
.badge { font-size:var(--fs-1); border-radius:4px; padding:2px 6px; margin-left:var(--sp-2); vertical-align:middle; } .badge-ai{background:#e3f2fd;color:#0d47a1;} .badge-manual{background:#fce4ec;color:#ad1457;}
.source-grade, .state-chip { display:inline-block; border-radius:3px; padding:1px 6px; font-size:.85em; } .source-grade--a,.state-chip--normal{background:#e8f5e9;color:#1b5e20;} .source-grade--b,.state-chip--transition{background:#fff3e0;color:#9c4400;} .source-grade--c{background:#ffebee;color:#b71c1c;}
.placeholder { color:#6b6b6b; border-bottom:1px dashed #999; font-style:italic; }
.dead-link { color:var(--ink-soft); border-bottom:1px dotted #b0bec5; cursor:default; }
.external-link::after { content:" ↗"; font-size:.75em; }
.auto-gen { border:1px dashed #90caf9; padding:var(--sp-3); border-radius:var(--radius); background:#fbfdff; } .auto-gen-meta { display:none; } .auto-gen-count { color:#37474f; background:#f5f8ff; padding:var(--sp-2) var(--sp-3); border-radius:6px; }
details { margin:var(--sp-2) 0; } summary { cursor:pointer; padding:var(--sp-2) var(--sp-3); border-left:3px solid transparent; } details[open] > summary { background:#f5f8ff; border-left-color:#2196f3; }
.course-index li { margin:var(--sp-2) 0; } .tag-deprecated { color:#555; background:#e8e8e8; border-radius:3px; padding:1px 5px; font-size:.8em; }
@media (max-width: 767px) { .site-header{gap:var(--sp-3) var(--sp-4); padding:var(--sp-3) var(--sp-4);} .course-page{padding:var(--sp-4);} h1{font-size:var(--fs-5);} table{font-size:var(--fs-2);} .button-link{display:block;margin:10px 0 0;} }
@media print { body{background:#fff;} .site-header,.site-footer,.status-banner,.badge,.jump-banner,.auto-gen-meta{display:none!important;} .course-page{max-width:none;padding:0;} a{color:#000;text-decoration:none;} tr, table { page-break-inside: avoid; } .breadcrumb{color:#000;} }
""".strip() + "\n"


def major_sources() -> list[tuple[str, Path]]:
    """Return (slug, index.md) for every major dir, sorted by slug."""
    out = []
    for d in sorted(MAJORS_DIR.iterdir()):
        if d.is_dir() and (d / "index.md").exists():
            out.append((d.name, d / "index.md"))
    return out


def build(out_dir: Path) -> BuildResult:
    result = BuildResult()
    site_root = out_dir.parent
    # Deterministic clean of this slice's outputs; preserve unrelated assets dir.
    for path in [out_dir, site_root / "majors", site_root / "index.html"]:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_css(site_root)

    majors = major_sources()
    stub_slugs = {slug for slug, src in majors if is_stub_major(read_text(src))}

    # Whitelist = routes this slice actually produces (IA-5 dead-link gate).
    pages = [load_course(path) for path in canonical_course_sources()]
    allowed = {"/", "/courses/", "/majors/", "/courses/15040-migration/"}
    allowed.update(p.route for p in pages)
    allowed.update(f"/courses/{c}/" for c in OLD_CODE_TARGETS)  # source pages exist
    allowed.update(f"/majors/{slug}/" for slug, _ in majors)
    CTX.allowed_routes = allowed
    CTX.warnings = result.warnings

    for page in pages:
        if page.code in OLD_CODE_TARGETS:
            html_text = render_old_code_page(page)
        else:
            html_text = render_course_page(page, result)
        target = site_root / slug_for_route(page.route)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
        result.pages += 1

    # Emit 15040.md as a noindex migration note to avoid treating it as body.
    migration_page = load_course(COURSES_DIR / "15040.md")
    migration_target = site_root / "courses" / "15040-migration" / "index.html"
    migration_target.parent.mkdir(parents=True, exist_ok=True)
    migration_target.write_text(render_migration_note(migration_page), encoding="utf-8")
    result.pages += 1

    index_target = site_root / "courses" / "index.html"
    index_target.parent.mkdir(parents=True, exist_ok=True)
    index_target.write_text(render_index(pages), encoding="utf-8")
    result.pages += 1

    # IA-1 site home.
    (site_root / "index.html").write_text(render_home(), encoding="utf-8")
    result.pages += 1

    # IA-3 major pages (4 real + 50 stub placeholders).
    for slug, src in majors:
        target = site_root / "majors" / slug / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_major_page(slug, src, result), encoding="utf-8")
        result.pages += 1

    # IA-2 majors index (direct render of existing majors/index.md).
    majors_index = site_root / "majors" / "index.html"
    majors_index.write_text(render_majors_index(stub_slugs), encoding="utf-8")
    result.pages += 1

    real_count = len(majors) - len(stub_slugs)
    report = [
        "# Course frontend build report",
        "",
        f"Pages generated: {result.pages}",
        "",
        "## Slice CHO-24 summary",
        f"- Home (IA-1): 1",
        f"- Majors index (IA-2): 1",
        f"- Major pages (IA-3): {len(majors)} ({real_count} real + {len(stub_slugs)} stub placeholder)",
        f"- Course detail + migration + index (IA-4): {len(pages)} + 1 migration + 1 index",
        "",
    ]
    if result.warnings:
        report.append("## Warnings")
        report.extend(f"- {w}" for w in result.warnings)
    else:
        report.append("No warnings.")
    if result.errors:
        report.append("## Errors")
        report.extend(f"- {e}" for e in result.errors)
    (site_root / "course-build-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
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
