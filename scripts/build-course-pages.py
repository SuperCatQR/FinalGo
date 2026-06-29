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
MAJORS_DIR = ROOT / "docs" / "jiangsu" / "majors"
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
class MajorPage:
    code: str
    name: str
    level: str
    slug: str
    source: Path
    route: str
    title: str
    meta: dict[str, str]
    body: str


@dataclass
class MajorIndexRow:
    num: str
    code: str
    name: str
    level: str
    slug: str
    exists: bool


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


def parse_major_index_rows(text: str) -> list[MajorIndexRow]:
    """Parse the majors/index.md table into structured rows."""
    lines = text.splitlines()
    rows: list[MajorIndexRow] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if stripped.startswith("| ---") or stripped.startswith("| :--"):
            in_table = True
            continue
        if not in_table:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        # Skip header row
        if cells[0] == "序号":
            continue
        num, code, name, level = cells[0], cells[1], cells[2], cells[3]
        link_cell = cells[4]
        slug_match = re.search(r"\]\(\./([^/)]+)/", link_cell)
        slug = slug_match.group(1) if slug_match else ""
        exists = (MAJORS_DIR / slug / "index.md").exists() if slug else False
        rows.append(MajorIndexRow(num=num, code=code, name=name, level=level, slug=slug, exists=exists))
    return rows


def load_major(path: Path, slug: str) -> MajorPage:
    raw = read_text(path)
    meta = parse_meta_table(raw)
    title = parse_heading_title(raw)
    code = meta.get("专业代码", "")
    name = meta.get("专业名称", title)
    level = meta.get("层次", "")
    return MajorPage(
        code=code,
        name=name,
        level=level,
        slug=slug,
        source=path,
        route=f"/majors/{slug}/",
        title=title,
        meta=meta,
        body=raw,
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
        return '<div class="status-banner status-banner--yellow">🤖 AI 辅助生成 — 本页面内容由 AI 依据官方考纲自动整理，可能存在错误。如与最新官方公告冲突，以官方为准。</div>'
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
    major_match = re.fullmatch(r"(?:\./|\.\./)+majors/([^/#?]+)(/)?([#?].*)?", href)
    if major_match:
        suffix = major_match.group(3) or ""
        return prefix_path(f"/majors/{major_match.group(1)}/{suffix}")
    match = re.fullmatch(r"(?:\./|\.\./)*(?:courses/)?(\d{5})(?:/|\.md)?", href)
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


# Signature blocks dropped from course pages per the CHO-94 product decision
# (AI 自动维护边界 = 不保留人工审核门槛): content goes in via pure AI
# auto-generation, so the manual sign-off region is not rendered. We strip
# only the heading + its body at render time — source markdown is untouched,
# and the reviewed正文 (everything before these H2s) is preserved.
REVIEW_SECTION_TITLES = ("人工审核清单", "AI 生成声明")


def strip_review_sections(body: str) -> str:
    """Drop the 人工审核清单 / AI 生成声明 H2 sections from a course body.

    A section runs from its `## <title>` line up to the next `## ` heading (or
    end of file). Everything outside these sections — including正文 already
    人工校对过 — is kept verbatim.
    """
    lines = body.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            skipping = any(title == t or title.startswith(t) for t in REVIEW_SECTION_TITLES)
            if skipping:
                continue
        elif skipping and stripped.startswith("# ") and not stripped.startswith("## "):
            # An H1 ends the skipped region too (defensive; course bodies use H2).
            skipping = False
        if skipping:
            continue
        out.append(line)
    return "".join(out)


def render_markdown(body: str, page: CoursePage | MajorPage | None = None) -> str:
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
    body = render_markdown(strip_review_sections(page.body), page)
    target_href = prefix_path(f"/courses/{target_code}/")
    majors_href = prefix_path("/majors/")
    banner = (
        f'<div class="jump-banner jump-banner--archive" role="alert">'
        f'{html.escape(message)}'
        f'<a class="button-link" href="{escape_attr(target_href)}">查看 {target_code} {html.escape(target_name)}</a>'
        f'</div>'
    )
    cross_jump = f'<nav class="cross-jump" aria-label="站内跳转"><a href="{escape_attr(majors_href)}">浏览全部专业</a></nav>'
    return html_shell(page.title, banner + body + cross_jump, canonical=prefix_path(f"/courses/{target_code}/"), noindex="noindex, follow")


def render_course_page(page: CoursePage, result: BuildResult) -> str:
    validate_page(page, result)
    body = render_markdown(strip_review_sections(page.body), page)
    count = parse_auto_gen_count(read_text(page.source))
    count_html = ""
    if page.code in PUBLIC_AUTO_GEN_CODES:
        count_html = f'<p class="auto-gen-count">适用专业统计：正常开考 {count["normal"]} 个，停考过渡 {count["transition"]} 个，合计 {count["total"]} 个。</p>'
    if page.code == "00023" and "AUTO_GEN_START" not in page.body:
        count_html = '<p class="contract-note">本课程无 AUTO_GEN 区域为正常契约，按人工维护/普通静态区块渲染。</p>'

    # Structured exam-index data island (B-2): emit parsed frontmatter as
    # machine-readable JSON so a dynamic frontend can partition "现行主流程 /
    # 历史题型对比" containers without parsing the flat markdown table.
    current_exam, legacy_exam = parse_exam_index_from_frontmatter(page.frontmatter)
    exam_index_json = ""
    if current_exam or legacy_exam:
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

    majors_href = prefix_path("/majors/")
    cross_jump = f'<nav class="cross-jump" aria-label="站内跳转"><a href="{escape_attr(majors_href)}">浏览全部专业</a></nav>'
    content = status_banner(page) + count_html + exam_index_json + body + cross_jump
    return html_shell(page.title, content, canonical=page.route)


def render_migration_note(page: CoursePage) -> str:
    target_href = prefix_path("/courses/15040/")
    content = f'<div class="migration-note">该文件是迁移说明页，不作为 15040 课程正文渲染。课程正文请访问 <a href="{escape_attr(target_href)}">/courses/15040/</a>。</div>' + render_markdown(strip_review_sections(page.body), page)
    return html_shell(page.title, content, canonical="/courses/15040/", noindex="noindex, follow")


def _head(title: str, canonical_href: str, noindex: str | None = None) -> str:
    """Shared <head>: two-layer stylesheet (base.css token contract + style-C
    theme.css signature), canonical, optional robots."""
    robots = f'<meta name="robots" content="{escape_attr(noindex)}">\n  ' if noindex else ""
    base_href = prefix_path("/assets/base.css")
    theme_href = prefix_path("/assets/theme.css")
    return f"""<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {robots}<link rel="canonical" href="{escape_attr(canonical_href)}">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="{escape_attr(base_href)}">
  <link rel="stylesheet" href="{escape_attr(theme_href)}">
</head>"""


def _header(active: str) -> str:
    """Shared top navigation header. active: 'home' | 'majors' | 'courses'."""
    home_href = prefix_path("/")
    majors_href = prefix_path("/majors/")
    courses_href = prefix_path("/courses/")

    def link(href: str, label: str, key: str) -> str:
        cur = ' aria-current="page"' if active == key else ""
        return f'<a href="{escape_attr(href)}"{cur}>{html.escape(label)}</a>'

    return f"""<header class="site-header"><div class="wrap">
    <a class="site-brand" href="{escape_attr(home_href)}">江苏自考资料库</a>
    <nav class="site-nav" aria-label="主导航">{link(home_href, "首页", "home")}{link(majors_href, "专业", "majors")}{link(courses_href, "课程", "courses")}</nav>
  </div></header>"""


_FOOTER = """<footer class="site-footer"><div class="wrap">
    <p class="footer-priority">数据源优先级：江苏省教育考试院官方公告与附件 &gt; 主考学校转发公告 &gt; 后续人工校对资料。</p>
    <p class="footer-note">本站为江苏自考资料参考，口径以江苏省教育考试院官方公告为准。</p>
  </div></footer>"""


def page_shell(title: str, breadcrumb: str, content: str, *, active: str,
               canonical_href: str, noindex: str | None = None) -> str:
    """Unified style-C page shell for all five page types: top nav + .wrap
    breadcrumb + centered .course-page main + footer. No sidebar — the
    style-C layout uses a sticky top nav (see CHO-94 prototype)."""
    bc = f'<nav class="breadcrumb" aria-label="面包屑"><div class="wrap">{breadcrumb}</div></nav>\n  ' if breadcrumb else ""
    return f"""<!doctype html>
<html lang="zh-CN">
{_head(title, canonical_href, noindex)}
<body>
  {_header(active)}
  {bc}<main>
    <div class="course-page">
      {content}
    </div>
  </main>
  {_FOOTER}
</body>
</html>
"""


def html_shell(title: str, content: str, canonical: str, noindex: str | None = None) -> str:
    home_href = prefix_path("/")
    courses_href = prefix_path("/courses/")
    breadcrumb = (
        f'<a href="{escape_attr(home_href)}">首页</a> &gt; '
        f'<a href="{escape_attr(courses_href)}">课程</a> &gt; {html.escape(title)}'
    )
    return page_shell(
        f"{title} · 江苏自考课程", breadcrumb, content,
        active="courses", canonical_href=prefix_path(canonical), noindex=noindex,
    )


def html_shell_major(title: str, content: str, canonical: str, name: str, level: str) -> str:
    """Shell for major detail pages — distinct breadcrumb from course pages."""
    home_href = prefix_path("/")
    majors_href = prefix_path("/majors/")
    title_full = f"{name}（{level}）" if level else name
    breadcrumb = (
        f'<a href="{escape_attr(home_href)}">首页</a> &gt; '
        f'<a href="{escape_attr(majors_href)}">专业</a> &gt; {html.escape(name)}'
    )
    return page_shell(
        f"{title_full} · 江苏自考专业", breadcrumb, content,
        active="majors", canonical_href=prefix_path(canonical),
    )


def html_shell_majors_index(title: str, content: str) -> str:
    """Shell for the majors index page."""
    home_href = prefix_path("/")
    breadcrumb = f'<a href="{escape_attr(home_href)}">首页</a> &gt; 专业'
    return page_shell(
        "江苏自考专业索引 · 江苏自考专业", breadcrumb, content,
        active="majors", canonical_href=prefix_path("/majors/"),
    )



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
    majors_href = prefix_path("/majors/")
    body += f'<nav class="cross-jump" aria-label="站内跳转"><a href="{escape_attr(majors_href)}">浏览全部专业</a></nav>'
    return html_shell("江苏自考课程页索引", body, canonical="/courses/")


def render_site_index() -> str:
    """Render site/index.html with base-aware paths, style-C shell."""
    majors = prefix_path("/majors/")
    body = f"""<h1>江苏自考资料库</h1>
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
</ul>"""
    return page_shell("江苏自考资料库", "", body, active="home", canonical_href=prefix_path("/"))


def render_majors_index(rows: list[MajorIndexRow], result: BuildResult) -> str:
    """Render site/majors/index.html from pre-parsed major index rows."""
    if not rows:
        return html_shell_majors_index("江苏自考专业索引", "<h1>江苏自考专业索引</h1><p>暂无专业数据</p>")

    # Build table rows with base-aware links
    table_rows: list[str] = []
    for row in rows:
        if row.exists:
            href = prefix_path(f"/majors/{row.slug}/")
            link = f'<a href="{escape_attr(href)}">{html.escape(row.name)}</a>'
        else:
            link = f'<span class="dead-link" title="专业页缺失，待内容团队补建">{html.escape(row.name)}</span>'
            result.warnings.append(f"majors/index.md: 专业 {row.code} {row.name} 目录缺失 ({row.slug}/)，已渲染为纯文本")
        table_rows.append(
            f"<tr>"
            f"<td>{html.escape(row.num)}</td>"
            f"<td><code>{html.escape(row.code)}</code></td>"
            f"<td>{link}</td>"
            f"<td>{html.escape(row.level)}</td>"
            f"</tr>"
        )

    search_html = """<noscript>
<style>.major-search{display:none}</style>
</noscript>
<div class="major-search">
  <label for="major-search-input" class="major-search-label">搜索专业：</label>
  <input type="search" id="major-search-input" class="major-search-input" placeholder="输入专业代码、名称或层次…" autocomplete="off">
  <span id="major-search-count" class="major-search-count"></span>
</div>
<script>
(function(){
  var input = document.getElementById('major-search-input');
  var count = document.getElementById('major-search-count');
  var tbody = document.querySelector('#major-table tbody');
  if (!input || !tbody) return;
  var rows = Array.from(tbody.querySelectorAll('tr'));
  function filter(){
    var q = input.value.trim().toLowerCase();
    var n = 0;
    rows.forEach(function(tr){
      var text = (tr.textContent || '').toLowerCase();
      var match = !q || text.indexOf(q) !== -1;
      tr.style.display = match ? '' : 'none';
      if (match) n++;
    });
    if (q) {
      count.textContent = n ? '找到 ' + n + ' 个专业' : '未找到匹配专业，请尝试其他关键词';
    } else {
      count.textContent = '';
    }
  }
  input.addEventListener('input', filter);
})();
</script>"""

    table_html = f"""<h1>江苏自考专业索引</h1>
{search_html}
<div class="table-scroll"><table id="major-table" class="responsive-table">
<thead><tr><th>序号</th><th>专业代码</th><th>专业名称</th><th>层次</th></tr></thead>
<tbody>
{"".join(table_rows)}
</tbody></table></div>"""

    return html_shell_majors_index("江苏自考专业索引", table_html)


def render_major_page(page: MajorPage, result: BuildResult) -> str:
    """Render a single major page HTML."""
    body = render_markdown(page.body, None)
    # Add cross-jump footer: browse all courses
    courses_href = prefix_path("/courses/")
    cross_jump = f'<nav class="cross-jump" aria-label="站内跳转"><a href="{escape_attr(courses_href)}">浏览全部课程</a></nav>'
    content = body + cross_jump
    return html_shell_major(page.title, content, page.route, page.name, page.level)


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

def write_css(out_root: Path) -> None:
    """Emit the two-layer stylesheet: base.css (token contract + structural
    primitives) + theme.css (style-C signature). Sedimented from the CHO-94
    prototype under scripts/templates/; the generator copies them verbatim so
    designers edit CSS as CSS, not as a Python string."""
    css_dir = out_root / "assets"
    css_dir.mkdir(parents=True, exist_ok=True)
    for name in ("base.css", "theme.css"):
        shutil.copyfile(TEMPLATES_DIR / name, css_dir / name)




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

    # --- Majors ---
    # Parse majors index once; pass rows to both index render and major page loop.
    major_rows = parse_major_index_rows(read_text(MAJORS_DIR / "index.md")) if (MAJORS_DIR / "index.md").exists() else []

    # Render majors index page
    majors_index_target = out_dir.parent / "majors" / "index.html"
    majors_index_target.parent.mkdir(parents=True, exist_ok=True)
    majors_index_target.write_text(render_majors_index(major_rows, result), encoding="utf-8")
    result.pages += 1

    # Render individual major pages
    for row in major_rows:
        if not row.exists:
            continue
        source = MAJORS_DIR / row.slug / "index.md"
        try:
            page = load_major(source, row.slug)
        except Exception as e:
            result.errors.append(f"majors/{row.slug}/: 解析失败：{e}，该专业页跳过")
            continue
        try:
            html_text = render_major_page(page, result)
        except Exception as e:
            result.errors.append(f"majors/{row.slug}/: 渲染失败：{e}，该专业页跳过")
            continue
        target = out_dir.parent / "majors" / row.slug / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
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
