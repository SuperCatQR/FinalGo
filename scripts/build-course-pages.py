#!/usr/bin/env python3
"""Build static HTML course pages from Jiangsu course Markdown files.

This is intentionally dependency-free so the Phase 1 frontend contract can be
validated in the current repository without introducing a site generator yet.

Phase 2 (CHO-10 B-1/B-2/B-3): publish-gate with blocking errors, exam-index
structured separation, and content_revision snapshot binding.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
COURSES_DIR = ROOT / "docs" / "jiangsu" / "courses"
DEFAULT_OUT_DIR = ROOT / "site" / "courses"
DEFAULT_BASE = "/"
V2_CODES = {"15040", "15043", "15044", "13000", "00023"}

# Module-level base path, set by main() via --base argument.
_base = DEFAULT_BASE


def set_base(path: str) -> None:
    """Set the base URL prefix for all absolute site paths."""
    global _base
    stripped = path.strip()
    if not stripped:
        raise SystemExit("--base must not be empty; use '/' for root deployment")
    if not stripped.startswith("/"):
        raise SystemExit(f"--base must start with '/'; got '{stripped}'")
    _base = stripped.rstrip("/") + "/"


def prefix_path(path: str) -> str:
    """Prefix an absolute site path with the current base.

    External URLs (http://, https://), anchors (#), and protocol-relative
    URLs (//) pass through unchanged.
    """
    if not path.startswith("/") or path.startswith("//"):
        return path
    if path.startswith(_base):
        return path
    return _base + path.lstrip("/")
OLD_CODE_TARGETS = {
    "03708": ("15043", "中国近现代史纲要"),
    "03709": ("15044", "马克思主义基本原理"),
}
PUBLIC_AUTO_GEN_CODES = {"15040", "15043", "15044", "13000"}
AUTO_GEN_START_MARKERS = ("<!-- AUTO-GEN-COVERAGE-START", "<!-- AUTO_GEN_START:public-course-coverage")
AUTO_GEN_END_MARKERS = ("<!-- AUTO-GEN-COVERAGE-END", "<!-- AUTO_GEN_END:public-course-coverage")

# ── content_revision snapshot (B-3) ──────────────────────────────────────────


def git_head_commit(repo_root: Path) -> str:
    """Return the HEAD commit hash, or empty string if unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


# ── exam-index structured fields (B-2) ───────────────────────────────────────


def parse_exam_index_from_frontmatter(fm: dict[str, str]) -> tuple[list[str], list[str]]:
    """Parse current_exam_periods / legacy_comparison_periods from frontmatter.

    Frontmatter format (whitespace-indented continuation lines):
        exam_index:
          current_exam_periods: [2024-10, 2025-04, 2025-10]
          legacy_comparison_periods: []
    """
    current: list[str] = []
    legacy: list[str] = []

    # The nested frontmatter is collapsed into single-line strings by
    # split_frontmatter; re-parse the YAML-like blocks.
    # Strategy: look for the raw keys in the combined frontmatter text.
    def _extract_list(raw: str, key: str) -> list[str]:
        # Match a JSON array or multi-line indented list.
        m = re.search(rf"{key}\s*:\s*\[([^\]]*)\]", raw)
        if m:
            items = [s.strip().strip("'\"") for s in m.group(1).split(",") if s.strip()]
            return [item for item in items if item]
        # Try multi-line with indented list items.
        m = re.search(rf"{key}\s*:\s*\n((?:\s+-\s+[^\n]+\n?)*)", raw)
        if m:
            items = re.findall(r"-\s+([^\n]+)", m.group(1))
            return [item.strip().strip("'\"") for item in items if item.strip()]
        return []

    current = _extract_list(raw_text_for_frontmatter(fm), "current_exam_periods")
    legacy = _extract_list(raw_text_for_frontmatter(fm), "legacy_comparison_periods")
    return current, legacy


def raw_text_for_frontmatter(fm: dict[str, str]) -> str:
    """Reconstruct a rough key-value text from the frontmatter dict for regex scanning."""
    return "\n".join(f"{k}: {v}" for k, v in fm.items())


# ── publish-gate target (B-1/B-3) ────────────────────────────────────────────

# Pages that are actively published (🟢 human_review_publishable) and must
# pass blocking validation.  During Phase 2 build, pages still at 🔴/🟡 only
# emit warnings; the gate blocks ONLY when a page claims publishable status.
PUBLISHABLE_STATUS_MARKER = "🟢"


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
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    content_revision: str = ""  # HEAD commit hash at build time (B-3)


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
    """Validate a course page against the publish-gate contract (B-1).

    Advisory warnings (always emitted):
      - E-R01: missing meta fields
      - E-R02: MIGRATION_STATUS != v2
      - E-R08: unparseable status
      - E-R16: missing AUTO_GEN markers on public courses

    Blocking errors (emitted when page claims 🟢 publishable status):
      - REPLACEMENT_FREE_TEXT_BYPASS: free-text replacement in body bypasses
        the structured 4-field table
      - PUBLISH_PENDING_REQUIRED_DATA: required fields still in pending state
      - HUMAN_REVIEW_REQUIRED: publishable but no human review signature
      - EXAM_INDEX_SCOPE_MIXED: old/new code exam periods mixed in one row
      - EXAM_INDEX_DUPLICATED_SCOPE: same exam_period+course_code in both
        current and legacy lists
      - CONTENT_REVISION_MISMATCH: page content_revision differs from build
        HEAD commit
    """
    required = ["省份", "课程代码", "课程名称", "学分", "状态", "版本号", "发布日期", "数据状态", "MIGRATION_STATUS"]
    publishable = page.meta.get("状态", "").startswith(PUBLISHABLE_STATUS_MARKER)

    # ── advisory warnings (always checked) ───────────────────────────────
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

    # ── blocking errors (only when page claims publishable) ──────────────
    if not publishable:
        return

    # B-1: REPLACEMENT_FREE_TEXT_BYPASS — blockquote replacement text
    # bypassing the structured 4-field table.
    if page.code in V2_CODES:
        _check_replacement_free_text_bypass(page, result)

    # B-1: PUBLISH_PENDING_REQUIRED_DATA — any required field still pending.
    _check_publish_pending(page, result)

    # B-1: HUMAN_REVIEW_REQUIRED — publishable without review signature.
    _check_human_review(page, result)

    # B-2: EXAM_INDEX_SCOPE_MIXED / EXAM_INDEX_DUPLICATED_SCOPE
    _check_exam_index_scope(page, result)

    # B-3: CONTENT_REVISION_MISMATCH
    _check_content_revision(page, result)


# ── B-1 sub-checks ───────────────────────────────────────────────────────────


def _check_replacement_free_text_bypass(page: CoursePage, result: BuildResult) -> None:
    """Block if replacement-relation section has free-text blockquote alongside the 4-field table."""
    in_replacement_section = False
    has_4field_table = False
    has_free_text = False
    lines = page.body.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## 新旧课程顶替"):
            in_replacement_section = True
            continue
        if in_replacement_section and stripped.startswith("## ") and "新旧课程顶替" not in stripped:
            break
        if not in_replacement_section:
            continue
        # Detect the 4-field structured table (header row "| 字段 | 内容 |")
        if stripped == "| 字段 | 内容 |":
            has_4field_table = True
            continue
        # Detect free-text blockquote in replacement section
        if stripped.startswith("> ") and "替代" in stripped:
            has_free_text = True
            continue
    if has_free_text and has_4field_table:
        result.errors.append(
            f"REPLACEMENT_FREE_TEXT_BYPASS: {page.source}: "
            "新旧课程顶替区块同时存在 4 字段结构化表和自由文本 blockquote，"
            "自由文本可能形成与结构化字段不一致的旁路。"
            "请移除 blockquote 中的顶替关系自由文本，仅保留 4 字段表。"
        )


def _check_publish_pending(page: CoursePage, result: BuildResult) -> None:
    """Block if required data is still in pending state."""
    pending_values = {"待补充", "待统计", "待收集", "待校对", "待确认", "待核验"}
    # Check meta table fields
    for key in ("数据状态", "发布日期"):
        val = page.meta.get(key, "")
        if any(pv in val for pv in pending_values):
            result.errors.append(
                f"PUBLISH_PENDING_REQUIRED_DATA: {page.source}: "
                f"元信息字段「{key}」仍处于待定状态（值：{val}），"
                f"不得标记为 🟢 可发布。"
            )
    # Check replacement relation confirmation status via frontmatter
    replacement_confirmed = page.frontmatter.get("replacement_confirmed", "")
    if replacement_confirmed and replacement_confirmed.lower() not in ("true", "yes", "confirmed"):
        result.errors.append(
            f"PUBLISH_PENDING_REQUIRED_DATA: {page.source}: "
            "顶替关系确认状态仍为 pending，不得标记为 🟢 可发布。"
        )
    # Check exam-index source_status / analysis_status in frontmatter
    for key in ("exam_source_status", "exam_analysis_status"):
        val = page.frontmatter.get(key, "")
        if any(pv in val for pv in pending_values):
            result.errors.append(
                f"PUBLISH_PENDING_REQUIRED_DATA: {page.source}: "
                f"真题数据字段「{key}」仍处于待定状态（值：{val}），"
                f"不得标记为 🟢 可发布。"
            )


def _check_human_review(page: CoursePage, result: BuildResult) -> None:
    """Block if page claims publishable but lacks human review signature."""
    reviewed = page.frontmatter.get("reviewed", "")
    reviewer = page.frontmatter.get("reviewer", "")
    if reviewed.lower() not in ("true", "yes"):
        result.errors.append(
            f"HUMAN_REVIEW_REQUIRED: {page.source}: "
            "页面标记为 🟢 可发布但缺少人工校对签名。"
            "请在 frontmatter 中设置 reviewed: true 和 reviewer: <姓名>。"
        )
    elif not reviewer:
        result.errors.append(
            f"HUMAN_REVIEW_REQUIRED: {page.source}: "
            "reviewed=true 但 reviewer 字段为空，"
            "人工校对签名不可追溯。请填写 reviewer。"
        )


# ── B-2 sub-checks ───────────────────────────────────────────────────────────


def _check_exam_index_scope(page: CoursePage, result: BuildResult) -> None:
    """Validate exam-index structured separation (B-2).

    Checks:
      - EXAM_INDEX_SCOPE_MIXED: a single exam-period table row references both
        15043 and 03708 (old/new mixed).
      - EXAM_INDEX_DUPLICATED_SCOPE: same exam_period appears in both
        current_exam_periods and legacy_comparison_periods frontmatter lists.
    """
    # 1. Scan the markdown exam-period table for mixed rows.
    in_exam_index = False
    lines = page.body.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## 考期索引"):
            in_exam_index = True
            continue
        if in_exam_index and stripped.startswith("## ") and "考期索引" not in stripped:
            break
        if not in_exam_index:
            continue
        if stripped.startswith("|") and not stripped.startswith("|---") and not stripped.startswith("| 考期"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            row_text = " ".join(cells)
            # Check if row mentions both old and new codes
            has_new = any(code in row_text for code in ("15043", "15044"))
            has_old = any(code in row_text for code in ("03708", "03709"))
            if has_new and has_old:
                result.errors.append(
                    f"EXAM_INDEX_SCOPE_MIXED: {page.source}: "
                    f"考期索引行混排新旧代码（{row_text[:60]}...），"
                    f"请拆分为 current_exam_periods 和 legacy_comparison_periods。"
                )

    # 2. Check frontmatter structured lists for dedup.
    current, legacy = parse_exam_index_from_frontmatter(page.frontmatter)
    if current and legacy:
        overlap = set(current) & set(legacy)
        if overlap:
            result.errors.append(
                f"EXAM_INDEX_DUPLICATED_SCOPE: {page.source}: "
                f"考期 {sorted(overlap)} 同时出现在 current_exam_periods 和 "
                f"legacy_comparison_periods 中，请移除重复项。"
            )


# ── B-3 sub-checks ───────────────────────────────────────────────────────────


def _check_content_revision(page: CoursePage, result: BuildResult) -> None:
    """Validate content_revision snapshot consistency (B-3).

    When the page frontmatter carries a content_revision field, it must match
    the build-time HEAD commit.  Mismatch means the page was validated against
    a different snapshot than what is being built.
    """
    page_rev = page.frontmatter.get("content_revision", "")
    if not page_rev:
        # No revision pinned yet — advisory only (not blocking).
        return
    build_rev = result.content_revision
    if not build_rev:
        return  # Can't compare without a build revision.
    if page_rev != build_rev:
        result.errors.append(
            f"CONTENT_REVISION_MISMATCH: {page.source}: "
            f"页面 content_revision={page_rev[:8]} 与构建 HEAD={build_rev[:8]} 不一致，"
            f"请重新校验后发布。"
        )


def render_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: render_link(html.unescape(m.group(1)), html.unescape(m.group(2))), escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def normalize_href(href: str) -> str:
    href = href.strip()
    if href.startswith("http://") or href.startswith("https://") or href.startswith("#") or href.startswith("//"):
        return href
    if href.startswith("/"):
        return prefix_path(href)
    major_match = re.fullmatch(r"(?:\./)?\.\./majors/([^/#?]+)(/)?([#?].*)?", href)
    if major_match:
        suffix = major_match.group(3) or ""
        return prefix_path(f"/majors/{major_match.group(1)}/{suffix}")
    match = re.fullmatch(r"(?:\./|\.\./)?(\d{5})(?:/|\.md)?", href)
    if match:
        return prefix_path(f"/courses/{match.group(1)}/")
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
    # Pending states must read as "not yet final", never as a confirmed
    # conclusion (contract: pending_confirmation/collection/validation ->
    # 待确认/待收集/待校验). Cover the in-content variants 待校对/待核验/待统计 too.
    if raw in {"待补充", "待统计", "待收集", "待校对", "待确认", "待校验", "待核验"} or "待补充" in raw:
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
        message = "📢 此页面为历史参考：自 2024 年 10 月考期起，『中国近现代史纲要』使用新代码 15043。现行有效页面为 15043。"
    else:
        message = "📢 此页面为历史参考：自 2024 年 10 月考期起，『马克思主义基本原理』使用新代码 15044。现行有效页面为 15044。"
    body = render_markdown(page.body, page)
    target_href = prefix_path(f"/courses/{target_code}/")
    banner = (
        f'<div class="jump-banner jump-banner--archive" role="alert">'
        f'{html.escape(message)}'
        f'<a class="button-link" href="{escape_attr(target_href)}">查看 {target_code} {html.escape(target_name)}</a>'
        f'</div>'
    )
    return html_shell(page.title, banner + body, canonical=prefix_path(f"/courses/{target_code}/"), noindex="noindex, follow")


def render_course_page(page: CoursePage, result: BuildResult) -> str:
    validate_page(page, result)
    body = render_markdown(page.body, page)
    count = parse_auto_gen_count(read_text(page.source))
    count_html = ""

    # Structured exam-index data island (B-2): emit parsed frontmatter as
    # machine-readable JSON so a dynamic frontend can partition "现行主流程 /
    # 历史题型对比" containers without parsing the flat markdown table.
    current_exam, legacy_exam = parse_exam_index_from_frontmatter(page.frontmatter)
    exam_index_json = ""
    if current_exam or legacy_exam:
        import json as _json
        exam_data = {
            "course_code": page.code,
            "current_exam_periods": current_exam,
            "legacy_comparison_periods": legacy_exam,
        }
        exam_index_json = (
            f'<script type="application/json" class="exam-index-data">'
            f'{html.escape(json.dumps(exam_data, ensure_ascii=False, separators=(",",":")))}'
            f'</script>'
        )

    if page.code in PUBLIC_AUTO_GEN_CODES:
        count_html = f'<p class="auto-gen-count">适用专业统计：正常开考 {count["normal"]} 个，停考过渡 {count["transition"]} 个，合计 {count["total"]} 个。</p>'
    if page.code == "00023" and "AUTO_GEN_START" not in page.body:
        count_html = '<p class="contract-note">本课程无 AUTO_GEN 区域为正常契约，按人工维护/普通静态区块渲染。</p>'
    content = status_banner(page) + count_html + exam_index_json + body
    return html_shell(page.title, content, canonical=page.route)


def render_migration_note(page: CoursePage) -> str:
    target_href = prefix_path("/courses/15040/")
    content = f'<div class="migration-note">该文件是迁移说明页，不作为 15040 课程正文渲染。课程正文请访问 <a href="{escape_attr(target_href)}">/courses/15040/</a>。</div>' + render_markdown(page.body, page)
    return html_shell(page.title, content, canonical="/courses/15040/", noindex="noindex, follow")


def html_shell(title: str, content: str, canonical: str, noindex: str | None = None) -> str:
    robots = f'<meta name="robots" content="{escape_attr(noindex)}">' if noindex else ""
    css_href = prefix_path("/assets/course.css")
    courses_href = prefix_path("/courses/")
    home_href = prefix_path("/")
    majors_href = prefix_path("/majors/")
    canonical_href = prefix_path(canonical)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {robots}
  <link rel="canonical" href="{escape_attr(canonical_href)}">
  <title>{html.escape(title)} · 江苏自考课程</title>
  <link rel="stylesheet" href="{escape_attr(css_href)}">
</head>
<body>
  <header class="site-header"><a href="{escape_attr(courses_href)}">江苏自考课程</a></header>
  <main class="course-page">
    <nav class="breadcrumb" aria-label="面包屑"><a href="{escape_attr(home_href)}">首页</a> &gt; <a href="{escape_attr(courses_href)}">课程</a> &gt; {html.escape(title)}</nav>
    {content}
  </main>
</body>
</html>
"""


def render_index(pages: Iterable[CoursePage]) -> str:
    current_items = []
    archive_items = []
    for page in sorted(pages, key=lambda p: p.code):
        label = f"{page.code} {page.meta.get('课程名称') or page.title}"
        if page.code in OLD_CODE_TARGETS:
            archive_items.append(f'<li><code>{page.code}</code> <a href="{escape_attr(prefix_path(page.route))}">{html.escape(label)}</a> <span class="tag-deprecated">已停用</span></li>')
        else:
            current_items.append(f'<li><code>{page.code}</code> <a href="{escape_attr(prefix_path(page.route))}">{html.escape(label)}</a></li>')
    body = "<h1>江苏自考课程页索引</h1>"
    body += "<h2>现行课程</h2><ul class=\"course-index\">" + "\n".join(current_items) + "</ul>"
    if archive_items:
        body += "<h2>历史存档</h2><ul class=\"course-index course-index--archive\">" + "\n".join(archive_items) + "</ul>"
    return html_shell("江苏自考课程页索引", body, canonical="/courses/")


def render_site_index() -> str:
    """Render site/index.html with base-aware paths, replacing the hand-written version."""
    home = prefix_path("/")
    majors = prefix_path("/majors/")
    courses = prefix_path("/courses/")
    css = prefix_path("/assets/course.css")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="canonical" href="{escape_attr(home)}">
  <title>江苏自考资料库 · 江苏自考资料库</title>
  <link rel="stylesheet" href="{escape_attr(css)}">
</head>
<body>
  <header class="site-header"><a class="site-brand" href="{escape_attr(home)}">江苏自考资料库</a><nav class="site-nav" aria-label="主导航"><a href="{escape_attr(home)}" aria-current="page">首页</a><a href="{escape_attr(majors)}">专业</a><a href="{escape_attr(courses)}">课程</a></nav></header>
  <main class="course-page">
    <h1>江苏自考资料库</h1>
<blockquote>数据源优先级：江苏省教育考试院官方公告与附件 &gt; 主考学校转发公告 &gt; 后续人工校对资料。</blockquote>
<h2>当前口径</h2>
<p>江苏省 2024 年发布《江苏省高等教育自学考试开考专业目录（2024年版）》和《江苏省高等教育自学考试专业考试计划（2024年版）》。本省样板页以"面向社会开考专业"为主，不覆盖全部助学/委托/高校内部口径。</p>
<h2>核心数字</h2>
<div class="table-scroll"><table class="responsive-table"><thead><tr><th>项目</th><th>结论</th></tr></thead><tbody><tr><td>面向社会开考专业</td><td>62 个</td></tr><tr><td>执行新考试计划专业</td><td>54 个</td></tr><tr><td>暂不调整考试计划专业</td><td>3 个：大数据与会计（专科）、现代农业经济管理（专科）、机械工程（专升本）</td></tr><tr><td>停考过渡专业</td><td>5 个：汉语言文学（专科）、英语（专科）、护理（专科）、监所管理（专升本）、心理健康教育（专升本）</td></tr><tr><td>新计划实施时间</td><td>2024 年 10 月考试起</td></tr><tr><td>过渡期</td><td>2024 年 7 月至 2026 年 6 月</td></tr></tbody></table></div>
<h2>内容入口</h2>
<ul>
<li><span class="dead-link" title="该入口本期未产出独立页面">江苏政策口径</span></li>
<li><span class="dead-link" title="该入口本期未产出独立页面">专业页批量生产工作流</span></li>
<li><span class="dead-link" title="该入口本期未产出独立页面">PDF 到 Markdown 四段式流水线</span></li>
<li><span class="dead-link" title="该入口本期未产出独立页面">PDF 批处理报告</span></li>
<li><a href="{escape_attr(majors)}">全量专业索引</a></li>
<li><span class="dead-link" title="该入口本期未产出独立页面">项目目录结构蓝图</span></li>
<li><a href="{escape_attr(prefix_path('/majors/030101K-law/'))}">法学（专升本）</a></li>
<li><a href="{escape_attr(prefix_path('/majors/050101-chinese-language-literature/'))}">汉语言文学（专升本）</a></li>
<li><a href="{escape_attr(prefix_path('/majors/120203K-accounting/'))}">会计学（专升本）</a></li>
<li><a href="{escape_attr(prefix_path('/majors/080901-computer-science-and-technology/'))}">计算机科学与技术（专升本）</a></li>
<li><span class="dead-link" title="该入口本期未产出独立页面">计算机科学与技术资料源清单</span></li>
<li><span class="dead-link" title="该入口本期未产出独立页面">计算机科学与技术课程资料采集矩阵</span></li>
<li><a href="{escape_attr(prefix_path('/courses/03708/'))}">中国近现代史纲要</a></li>
<li><a href="{escape_attr(prefix_path('/courses/03709/'))}">马克思主义基本原理概论</a></li>
<li><a href="{escape_attr(prefix_path('/courses/13000/'))}">英语（专升本）</a></li>
</ul>
<h2>官方来源</h2>
<ul>
<li>江苏省教育考试院：《关于江苏省高等教育自学考试面向社会开考专业及考试计划调整有关事项的通告》</li>
<li>附件 1：《江苏省高等教育自学考试面向社会开考专业目录（2024年版）》</li>
<li>附件 2：《江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）》</li>
<li>附件 3：《江苏省高等教育自学考试面向社会开考专科专业新旧代码和名称对照表》</li>
<li>附件 4：《江苏省高等教育自学考试专业考试计划简编（2024年版）》</li>
</ul>
  </main>
  <footer class="site-footer"><p class="footer-priority">数据源优先级：江苏省教育考试院官方公告与附件 &gt; 主考学校转发公告 &gt; 后续人工校对资料。</p><p class="footer-note">本站为江苏自考资料参考，口径以江苏省教育考试院官方公告为准。</p></footer>
</body>
</html>
"""


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
.jump-banner--archive { background:#fff3e0; border:1px solid #ff9800; border-left:4px solid #e65100; color:#7a3b00; font-weight:600; }
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
    result.content_revision = git_head_commit(ROOT)
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

    # Render site/index.html from script to eliminate hardcoded paths.
    site_index_target = out_dir.parent / "index.html"
    site_index_target.write_text(render_site_index(), encoding="utf-8")
    result.pages += 1

    report = ["# Course frontend build report", "", f"Pages generated: {result.pages}", ""]
    if result.content_revision:
        report.append(f"Build revision: `{result.content_revision}`")
        report.append("")
    if result.warnings:
        report.append("## Warnings")
        report.extend(f"- {w}" for w in result.warnings)
    else:
        report.append("No warnings.")
    if result.errors:
        report.append("## Errors (blocking)")
        report.extend(f"- {e}" for e in result.errors)
    (out_dir.parent / "course-build-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build static course HTML pages")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for /courses pages")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Base URL path prefix (default: /, set to e.g. /FinalGo/ for project-page deployments)")
    args = parser.parse_args()
    set_base(args.base)
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
