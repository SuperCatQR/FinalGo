# 江苏自考课程页 🟡→🟢 人工校对 Checklist（样板：15044 马原）

> 本 checklist 由 15044 马原跑通的「机器初稿 → 逐项校对 → 🟢」闭环沉淀而来，供首批其余 7 门
> （15043、15040、13000、00023、04735、04747、13003）直接套用。
>
> 分两层：**A. 机器可验证项**（脚本/构建门禁自动卡，提交前必须全绿）；
> **B. 人工校对项**（高风险区块，须 SME 逐项签名，机器无法替代）。
> 任一 B 项未签名 → 不得置 🟢。

## 0. 校对前置：锁定 source-of-truth

- [ ] 官方考纲已入库并完成机器抽取：`docs/jiangsu/source/processed/syllabus/<slug>/document.extracted.md`
- [ ] 校对一律以 **该 extracted.md（官方考纲原文）** 为准；机器初稿与官方原文冲突时，**以官方为准**修正，并在「版本历史」记一行
- [ ] 冲突无法判定（学分/章节/版本三者互斥、官方多版本不一致）→ 按 [[blocker-protocol]] 报阻塞，不擅自取舍

## A. 机器可验证项（提交前 `python scripts/build-course-pages.py` 必须 0 error）

构建门禁（`scripts/build-course-pages.py`）在页面标记 🟢 时会强制以下检查，未过 = 直接 block：

- [ ] **A1 数据状态/发布日期无待定值**：meta 表「数据状态」「发布日期」不得含 `待补充/待统计/待收集/待校对/待确认/待核验`（`PUBLISH_PENDING_REQUIRED_DATA`）
- [ ] **A2 人工校对签名**：frontmatter `reviewed: true` 且 `reviewer: <真实姓名/Git author>` 非空（`HUMAN_REVIEW_REQUIRED`）—— 此项由 B 层签名完成后回填
- [ ] **A3 顶替关系无自由文本旁路**：「新旧课程顶替」区块只保留 4 字段结构化表，不得再有含「替代」的自由文本 blockquote（`REPLACEMENT_FREE_TEXT_BYPASS`）
- [ ] **A4 顶替确认状态**：若 frontmatter 有 `replacement_confirmed`，值须为 `true/yes/confirmed`，不得为 `pending_confirmation`
- [ ] **A5 考期索引新旧不混排**：考期表单行不得同时出现新旧代码；新旧分入 `current_exam_periods` / `legacy_comparison_periods` 且无重叠（`EXAM_INDEX_SCOPE_MIXED` / `EXAM_INDEX_DUPLICATED_SCOPE`）
- [ ] **A6 真题数据状态**：若 frontmatter 有 `exam_source_status` / `exam_analysis_status`，不得为待定值
- [ ] **A7 content_revision**：如已 pin，须与构建 HEAD 一致（`CONTENT_REVISION_MISMATCH`）
- [ ] **A8 来源链接**：`python scripts/check-source-links.py` 无 dead-link（超时/DNS/TLS 失败记为 inconclusive，非死链，不卡）
- [ ] **A9 16 必填区块齐全**：按 IA.md §3 顺序 16 区块缺一不可；空数据以**空态**保留区块并注明原因+待办，不得删区块

## B. 人工校对项（高风险，SME 逐项签名，复用 15044 的 17 项审核清单）

逐项对照「0. source-of-truth」核验，签名格式：`[x] <项> — 校对人 <姓名> @ <Git commit / 日期>`

- [ ] B1 课程代码、名称与官方专业计划一致
- [ ] B2 学分与官方计划一致
- [ ] B3 考纲链接可访问 或 本地 PDF 路径有效
- [ ] B4 教材版本为当前考期有效版本（版本年份 + ISBN，ISBN 须实物/出版社官网核验，不得编造）
- [ ] B5 章节知识树与考纲目录结构一致，知识点覆盖率 ≥ 90%
- [ ] B6 高频概念无凭空编造，考频排序**有真题统计依据**（无真题则考频标空态「待统计」，不得伪造排序）
- [ ] B7 真题解析**不含第三方原题全文**（版权红线，必带 **法务合规团队** 审视）
- [ ] B8 解题思路为通用方法论，不绑定具体考题题号和参数
- [ ] B9 AI 生成内容已标注且经人工校对，校对签名可追溯至 Git commit
- [ ] B10 新旧代码顶替关系使用标准 4 字段格式
- [ ] B11 适用专业清单完整，来源标注自动生成时间戳（公共课须全量专业，非单专业占位）
- [ ] B12 旧代码页面有醒目跳转链接
- [ ] B13 「政策与时效」节内容准确
- [ ] B14 「来源与引用」节格式与专业页模板一致
- [ ] B15 所有日期使用实际日期非占位符
- [ ] B16 面包屑导航可用
- [ ] B17 Markdown 格式规范，链接有效，打印可读

## C. 合规联动（置 🟢 前必须触发，否则不得发布）

- [ ] 涉版权区块（真题/教材 ISBN）→ 显式带 **法务合规团队** 审视（B4 / B7）
- [ ] 涉考生 PII 区块 → 法务合规团队审视（按 [[data-compliance-cn]]）
- [ ] AI 生成声明区块完整，顶部 ⚠️ 横幅在 🟢 后按状态语义处理

## D. 三态验收（Given-When-Then，对齐父 CHO-106）

- **正常态**：必填区块齐全 + 字数达标 + B 层 17 项逐项签名 + 来源链接校验 → 置 🟢，移除 ⚠️ 横幅，清单全勾
- **空态**：某区块官方数据暂缺（真题未采集/考频未统计）→ 空态保留区块并注明原因与待办，不删不造；空态不计入未完成，页面仍可 🟢
- **异常态**：机器抽取与官方考纲/教材冲突 → 以官方原文为准修正并记版本历史；无法判定 → [[blocker-protocol]] 报阻塞

---

### 套用说明（其余 7 门）

1. 先确认该门官方考纲已入库 + 机器抽取（步骤 0）。
2. 跑 A 层脚本，修干净所有 error。
3. SME 对照官方 extracted.md 逐项签 B1–B17，签名写进 frontmatter `reviewed/reviewer` + 「AI 生成声明」表的校对签名列。
4. 涉版权/PII 区块走 C 层法务合规审视。
5. 全绿后置 🟢，按 [[squad-handoff]] assign 质量保障团队提测。
