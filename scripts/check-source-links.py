#!/usr/bin/env python3
"""Detect changes in 考纲 / 来源 links referenced by Jiangsu course pages.

This implements the "考纲链接变更主动检测机制" (CHO-14): periodically verify the
accessibility of every external source URL referenced in the「来源与引用」/「真题索引」/
「考纲与教材」sections, and compare each authoritative 考纲 page against a recorded
content hash. Drift (a link that went dead, or an authoritative page whose content
changed) is reported and mapped to the PRD §4.2 双向状态回退 recommendation
(🟢→🟡 / 🟡→🔴) so a maintainer can apply the degradation.

Design goals (matches scripts/build-course-pages.py):
- Dependency-free (stdlib urllib only) so it runs in CI without a venv.
- Network-fault tolerant: a timeout / DNS / TLS failure is classified as
  ``inconclusive`` (NOT a dead link), so geo-blocking of CN sites from a foreign
  CI runner does not produce false 🔴 degradations.
- Bulk-rot aware: if most URLs of one host go dead together (e.g. a 省级网站改版),
  that is flagged as a host-level event instead of N independent page degradations.

The script never edits course Markdown. It only detects + reports; applying the
status degradation is a content-side action (see the runbook).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
COURSES_DIR = ROOT / "docs" / "jiangsu" / "courses"
MAJORS_DIR = ROOT / "docs" / "jiangsu" / "majors"
DEFAULT_BASELINE = ROOT / "docs" / "jiangsu" / "source-links.baseline.json"
DEFAULT_REPORT = ROOT / "site" / "source-link-report.md"
DEFAULT_SUMMARY = ROOT / "site" / "source-link-report.json"

# Hosts whose pages are authoritative 考纲/教材/计划 sources. Content drift on
# these matters (it can mean the 考纲 was revised), so we hash and diff them.
# Non-authoritative reference/真题 sites (zikaosw, zikao365, bilibili) carry ads
# and rotating markup, so a hash diff there is noise -- we only track liveness.
AUTHORITATIVE_HOSTS = {
    "www.jseea.cn",
    "jseea.cn",
    "www.jseea.com.cn",
}

# Section headings whose links are in scope. We tag each URL with the nearest
# preceding ``##``/``###`` heading so the report can say which section rotted.
IN_SCOPE_SECTION_KEYWORDS = (
    "来源与引用",
    "考纲与教材",
    "真题索引",
    "真题",
    "官方来源",
    "来源",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "FinalGo-source-link-monitor/1.0 (+https://github.com/SuperCatQR/FinalGo)"
)

# Classification of a single probe.
STATUS_OK = "ok"               # reachable, 2xx/3xx
STATUS_DEAD = "dead"           # reachable server, but 4xx/5xx (real rot)
STATUS_INCONCLUSIVE = "inconclusive"  # timeout / DNS / TLS / connection refused

MD_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^\s)]+)\)")
BARE_URL_RE = re.compile(r"(?<![(\[])\bhttps?://[^\s)\]<>`\"']+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class UrlRef:
    """A single occurrence of a URL inside a course/major markdown file."""

    url: str
    source_file: str
    section: str
    course_code: str | None


@dataclass
class ProbeResult:
    url: str
    status: str                 # STATUS_OK / STATUS_DEAD / STATUS_INCONCLUSIVE
    http_code: int | None = None
    content_hash: str | None = None  # only for authoritative hosts that returned OK
    detail: str = ""


@dataclass
class UrlFinding:
    url: str
    host: str
    authoritative: bool
    refs: list[UrlRef] = field(default_factory=list)
    probe: ProbeResult | None = None
    # Set during baseline diff:
    change: str | None = None   # None | "new" | "went_dead" | "content_changed" | "recovered"
    baseline_status: str | None = None
    baseline_hash: str | None = None

    @property
    def course_codes(self) -> list[str]:
        return sorted({r.course_code for r in self.refs if r.course_code})

    @property
    def sections(self) -> list[str]:
        return sorted({r.section for r in self.refs if r.section})


def host_of(url: str) -> str:
    try:
        return urllib.request.urlparse(url).hostname or ""
    except ValueError:
        return ""


def normalize_url(url: str) -> str:
    # Strip trailing punctuation that markdown prose tends to glue onto bare URLs.
    return url.rstrip(".,;:。，、)）]】>")


def section_in_scope(section: str) -> bool:
    return any(kw in section for kw in IN_SCOPE_SECTION_KEYWORDS)


def course_code_for(path: Path) -> str | None:
    """Infer the 5-digit course code from a course markdown path, else None."""
    stem = path.stem
    if re.fullmatch(r"\d{5}", stem):
        return stem
    if path.name == "index.md" and re.fullmatch(r"\d{5}", path.parent.name):
        return path.parent.name
    return None


def iter_source_files() -> Iterable[Path]:
    """All markdown files that may carry in-scope source links."""
    for path in sorted(COURSES_DIR.glob("*.md")):
        yield path
    # 15040 canonical body lives in a subdir.
    nested = COURSES_DIR / "15040" / "index.md"
    if nested.exists():
        yield nested
    for path in sorted(MAJORS_DIR.glob("*/index.md")):
        yield path
    for path in sorted(MAJORS_DIR.glob("*/sources.md")):
        yield path


def extract_refs(path: Path) -> list[UrlRef]:
    """Pull every in-scope external URL out of one markdown file, tagged by section."""
    refs: list[UrlRef] = []
    code = course_code_for(path)
    rel = path.relative_to(ROOT).as_posix()
    current_section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            current_section = heading.group(2).strip()
            continue
        if not section_in_scope(current_section):
            continue
        seen_on_line: set[str] = set()
        for match in MD_LINK_RE.finditer(line):
            url = normalize_url(match.group(1))
            seen_on_line.add(url)
            refs.append(UrlRef(url, rel, current_section, code))
        for match in BARE_URL_RE.finditer(line):
            url = normalize_url(match.group(0))
            if url in seen_on_line:
                continue
            seen_on_line.add(url)
            refs.append(UrlRef(url, rel, current_section, code))
    return refs


def collect_findings() -> dict[str, UrlFinding]:
    findings: dict[str, UrlFinding] = {}
    for path in iter_source_files():
        for ref in extract_refs(path):
            finding = findings.get(ref.url)
            if finding is None:
                host = host_of(ref.url)
                finding = UrlFinding(
                    url=ref.url,
                    host=host,
                    authoritative=host in AUTHORITATIVE_HOSTS,
                )
                findings[ref.url] = finding
            finding.refs.append(ref)
    return findings


def _decode_body(raw: bytes, encoding_header: str | None) -> bytes:
    enc = (encoding_header or "").lower()
    try:
        if "gzip" in enc:
            return gzip.decompress(raw)
        if "deflate" in enc:
            return zlib.decompress(raw)
    except (OSError, zlib.error):
        return raw
    return raw


def _content_fingerprint(body: bytes) -> str:
    """Hash of the body with volatile bits stripped, to reduce false drift.

    Authoritative 考纲 pages (jseea.cn) embed rotating tokens / timestamps; we drop
    long digit runs and common cache-buster query echoes before hashing so only a
    real content revision changes the fingerprint.
    """
    text = body.decode("utf-8", errors="ignore")
    # Collapse whitespace and strip long digit runs (timestamps, view counters, ids).
    text = re.sub(r"\d{6,}", "#", text)
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def probe(url: str, *, authoritative: bool, timeout: float, retries: int) -> ProbeResult:
    """Fetch a URL and classify the outcome. Never raises."""
    ctx = ssl.create_default_context()
    last_detail = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            method="GET" if authoritative else "HEAD",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                code = resp.getcode()
                content_hash = None
                if authoritative:
                    raw = resp.read(2_000_000)  # cap at ~2MB; we only need a fingerprint
                    body = _decode_body(raw, resp.headers.get("Content-Encoding"))
                    content_hash = _content_fingerprint(body)
                return ProbeResult(url, STATUS_OK, http_code=code, content_hash=content_hash)
        except urllib.error.HTTPError as exc:
            # Some servers reject HEAD with 403/405; retry once with GET before judging.
            if exc.code in (403, 405, 501) and req.get_method() == "HEAD" and attempt < retries:
                last_detail = f"HEAD {exc.code}, retrying with GET"
                req2 = urllib.request.Request(
                    url, method="GET",
                    headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
                )
                try:
                    with urllib.request.urlopen(req2, timeout=timeout, context=ctx) as resp:
                        return ProbeResult(url, STATUS_OK, http_code=resp.getcode())
                except urllib.error.HTTPError as exc2:
                    return ProbeResult(url, STATUS_DEAD, http_code=exc2.code,
                                       detail=f"HTTP {exc2.code} {exc2.reason}")
                except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as exc2:
                    last_detail = f"{type(exc2).__name__}: {exc2}"
                    continue
            return ProbeResult(url, STATUS_DEAD, http_code=exc.code,
                               detail=f"HTTP {exc.code} {exc.reason}")
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2.0, 0.5 * (attempt + 1)))
            continue
    return ProbeResult(url, STATUS_INCONCLUSIVE, detail=last_detail or "unreachable")


def load_baseline(path: Path) -> dict:
    if not path.exists():
        return {"generated_at": None, "urls": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"generated_at": None, "urls": {}}


def diff_against_baseline(findings: dict[str, UrlFinding], baseline: dict) -> None:
    """Annotate each finding with its change vs the recorded baseline (in place)."""
    base_urls: dict = baseline.get("urls", {})
    for finding in findings.values():
        probe = finding.probe
        assert probe is not None
        base = base_urls.get(finding.url)
        if base is None:
            finding.change = "new"
            continue
        finding.baseline_status = base.get("status")
        finding.baseline_hash = base.get("content_hash")
        # Liveness transitions (only act on a definitive dead, never inconclusive).
        if probe.status == STATUS_DEAD and finding.baseline_status == STATUS_OK:
            finding.change = "went_dead"
        elif probe.status == STATUS_OK and finding.baseline_status == STATUS_DEAD:
            finding.change = "recovered"
        elif (
            finding.authoritative
            and probe.status == STATUS_OK
            and probe.content_hash
            and finding.baseline_hash
            and probe.content_hash != finding.baseline_hash
        ):
            finding.change = "content_changed"


# Degradation recommendation per PRD §4.2 双向状态回退规则表.
DEGRADE_BY_CHANGE = {
    "went_dead": "🟡→🔴 (考纲链接失效：内容无可信来源支撑，降级至骨架级)",
    "content_changed": "🟢→🟡 (考纲内容变更：已校对内容需重新核对，降级至 AI 待校对)",
}


def bulk_rot_hosts(findings: dict[str, UrlFinding]) -> dict[str, dict]:
    """Detect host-level rot: a host where >=60% (and >=3) of its URLs went dead.

    Such an event is reported as ONE host alert, not N page degradations, because
    it usually means a 省级网站改版 — a maintainer should re-locate the new URLs
    rather than blindly 🔴 every affected course.
    """
    by_host: dict[str, list[UrlFinding]] = {}
    for f in findings.values():
        by_host.setdefault(f.host, []).append(f)
    alerts: dict[str, dict] = {}
    for host, group in by_host.items():
        dead = [f for f in group if f.probe and f.probe.status == STATUS_DEAD]
        if len(group) >= 3 and len(dead) >= 3 and len(dead) / len(group) >= 0.6:
            alerts[host] = {
                "total": len(group),
                "dead": len(dead),
                "dead_urls": sorted(f.url for f in dead),
            }
    return alerts


def serialize_baseline(findings: dict[str, UrlFinding]) -> dict:
    urls = {}
    for url, f in sorted(findings.items()):
        probe = f.probe
        assert probe is not None
        urls[url] = {
            "status": probe.status,
            "http_code": probe.http_code,
            "authoritative": f.authoritative,
            "content_hash": probe.content_hash,
            "course_codes": f.course_codes,
            "sections": f.sections,
        }
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Baseline for scripts/check-source-links.py (CHO-14). "
                "inconclusive probes are NOT persisted as status changes.",
        "urls": urls,
    }


def build_report(findings: dict[str, UrlFinding], bulk: dict[str, dict]) -> tuple[str, dict]:
    """Return (markdown_report, json_summary)."""
    total = len(findings)
    ok = sum(1 for f in findings.values() if f.probe and f.probe.status == STATUS_OK)
    dead = sum(1 for f in findings.values() if f.probe and f.probe.status == STATUS_DEAD)
    incon = sum(1 for f in findings.values() if f.probe and f.probe.status == STATUS_INCONCLUSIVE)

    actionable = [f for f in findings.values()
                  if f.change in ("went_dead", "content_changed")]
    new_urls = [f for f in findings.values() if f.change == "new"]
    recovered = [f for f in findings.values() if f.change == "recovered"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# 考纲/来源链接变更检测报告",
        "",
        f"- 生成时间：{now}",
        f"- 链接总数：{total}（可访问 {ok} · 失效 {dead} · 网络不确定 {incon}）",
        f"- 需处理变更：{len(actionable)} · 新增链接：{len(new_urls)} · 恢复：{len(recovered)}",
        f"- 批量腐烂主机：{len(bulk)}",
        "",
    ]

    if bulk:
        lines += ["## ⚠️ 批量链接腐烂（疑似站点改版）", ""]
        for host, info in sorted(bulk.items()):
            lines.append(
                f"- `{host}`：{info['dead']}/{info['total']} 链接同时失效，"
                "疑似省级网站改版，请人工重新定位新入口而非逐页降级。"
            )
        lines.append("")

    if actionable:
        lines += ["## 🔴 需降级处理（PRD §4.2）", "",
                  "| URL | 变更 | 涉及课程 | 章节 | 建议降级 |",
                  "| --- | --- | --- | --- | --- |"]
        for f in sorted(actionable, key=lambda x: x.url):
            host_bulk = " (属批量腐烂，先核站点)" if f.host in bulk else ""
            codes = ", ".join(f.course_codes) or "—"
            secs = ", ".join(f.sections) or "—"
            rec = DEGRADE_BY_CHANGE.get(f.change, "—") + host_bulk
            detail = f.probe.detail if f.probe else ""
            lines.append(f"| {f.url} | {f.change} {detail} | {codes} | {secs} | {rec} |")
        lines.append("")

    if new_urls:
        lines += ["## 🆕 新增链接（已纳入基线，无需处理）", ""]
        for f in sorted(new_urls, key=lambda x: x.url):
            status = f.probe.status if f.probe else "?"
            lines.append(f"- {f.url} — {status}（{', '.join(f.course_codes) or '专业页'}）")
        lines.append("")

    if recovered:
        lines += ["## ✅ 已恢复", ""]
        for f in sorted(recovered, key=lambda x: x.url):
            lines.append(f"- {f.url}（{', '.join(f.course_codes) or '专业页'}）")
        lines.append("")

    if incon:
        lines += ["## 🌐 网络不确定（不计入失效，不触发降级）", ""]
        for f in sorted(findings.values(), key=lambda x: x.url):
            if f.probe and f.probe.status == STATUS_INCONCLUSIVE:
                lines.append(f"- {f.url} — {f.probe.detail}")
        lines.append("")

    if not (actionable or bulk):
        lines += ["## 结论", "", "本次检测未发现需降级的考纲链接变更。", ""]

    summary = {
        "generated_at": now,
        "totals": {"total": total, "ok": ok, "dead": dead, "inconclusive": incon},
        "actionable": [
            {
                "url": f.url, "change": f.change, "course_codes": f.course_codes,
                "sections": f.sections, "recommendation": DEGRADE_BY_CHANGE.get(f.change),
                "in_bulk_host": f.host in bulk,
            }
            for f in sorted(actionable, key=lambda x: x.url)
        ],
        "bulk_rot_hosts": bulk,
        "new_urls": [f.url for f in sorted(new_urls, key=lambda x: x.url)],
        "recovered": [f.url for f in sorted(recovered, key=lambda x: x.url)],
        "actionable_count": len(actionable),
        "bulk_rot_count": len(bulk),
    }
    return "\n".join(lines) + "\n", summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect 考纲/来源 link changes for Jiangsu course pages (CHO-14)")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE),
                        help="Path to the baseline JSON manifest")
    parser.add_argument("--report", default=str(DEFAULT_REPORT),
                        help="Path to write the Markdown report")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY),
                        help="Path to write the JSON summary (for CI consumption)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="Persist current probe results as the new baseline")
    parser.add_argument("--init-baseline", action="store_true",
                        help="Create the baseline from current probes and skip diff reporting")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout (s)")
    parser.add_argument("--retries", type=int, default=1, help="Retries on network fault")
    parser.add_argument("--offline", action="store_true",
                        help="Skip network probes (extraction smoke test only)")
    parser.add_argument("--fail-on-change", action="store_true",
                        help="Exit non-zero if actionable changes are found (strict CI gate)")
    args = parser.parse_args()

    findings = collect_findings()
    if not findings:
        print("[WARN] no in-scope source URLs found", flush=True)

    if args.offline:
        for f in findings.values():
            f.probe = ProbeResult(f.url, STATUS_INCONCLUSIVE, detail="offline mode")
        print(f"Extracted {len(findings)} unique URLs from "
              f"{len(list(iter_source_files()))} source files (offline; no probes).")
        for f in sorted(findings.values(), key=lambda x: x.url):
            print(f"  {f.url}  [{', '.join(f.course_codes) or 'major'}]  «{', '.join(f.sections)}»")
        return 0

    print(f"Probing {len(findings)} URLs (timeout={args.timeout}s, retries={args.retries})...",
          flush=True)
    for i, (url, f) in enumerate(sorted(findings.items()), 1):
        f.probe = probe(url, authoritative=f.authoritative,
                        timeout=args.timeout, retries=args.retries)
        print(f"  [{i}/{len(findings)}] {f.probe.status:12} {url} "
              f"{('('+f.probe.detail+')') if f.probe.detail else ''}", flush=True)

    baseline_path = Path(args.baseline)
    if not args.init_baseline:
        baseline = load_baseline(baseline_path)
        diff_against_baseline(findings, baseline)
    bulk = bulk_rot_hosts(findings)

    report_md, summary = build_report(findings, bulk)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"\nReport: {report_path}")
    print(f"Summary: {summary_path}")
    print(f"Actionable changes: {summary['actionable_count']} · "
          f"bulk-rot hosts: {summary['bulk_rot_count']}")

    if args.update_baseline or args.init_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(serialize_baseline(findings), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"Baseline written: {baseline_path}")

    if args.fail_on_change and summary["actionable_count"] > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())






