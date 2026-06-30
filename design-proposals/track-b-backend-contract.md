# 轨道 B 后端交付包 — 实现方向 + 接口/数据契约

> 对应 issue CHO-107（父 CHO-105）。本文档由后端整合产出，作为前端对接与后端审查的唯一基准。
> 范围：B-1 站内静态全文检索 + B-2 PDF→课程页机器初稿写入管道。
> **本期不改路由结构、不引入检索后端/外部依赖、不新增持久化层。**

## 0. 关键结论（先读）

- **无 HTTP API、无数据库**。本站是 Git 为数据源、`scripts/build-course-pages.py` 生成静态 HTML 的静态站。B-1 检索是「构建期产出静态索引 JSON + 浏览器端纯 JS 过滤」，B-2 写入是「脚本产出 `docs/` 下 Markdown 初稿」。因此 [[api-contract-spec]] 的 HTTP 统一信封 / 错误码段位 / 鉴权**不适用**——没有服务端就没有这些层。本文用「静态产物 schema + 客户端降级三态」替代，下文 §1.4 显式做映射。
- **无 Schema 变更 → 不走 DBA。** 索引产物是构建副产物（写进 `site/`，已被 `.gitignore` 忽略，随构建再生）；初稿产物是 `docs/` 下的 Markdown 文本，归 Git 版本管理。两者都不引入数据库或持久化结构。若后续审查认为需要独立索引服务/DB，属另起切片，按 [[db-migration-safe]] 提 DBA，本期不做。
- **合规前置**：AI 生成声明机制、真题/教材版权 → 交付测试/部署前**必须显式带上法务合规团队**终审（见 §5）。

## 1. B-1 站内全文检索

### 1.1 实现方向

- 在 `scripts/build-course-pages.py` 的 `build()` 末尾新增一步，遍历已加载的 `pages`（课程）与 `major_rows`（专业），产出单个静态文件 `site/search-index.json`。
- 前端检索 UI = 纯 vanilla JS：`fetch('search-index.json')` → 内存过滤 → 渲染结果列表。**复用现有先例**：`majors/index.md` 已内置对表格的 JS 即时过滤（`major-search-input`，含空态文案「未找到匹配专业，请尝试其他关键词」），B-1 把同样的模式从「单页表格」升级为「跨页 JSON 索引」，不新造机制。
- 状态来源：构建脚本已有 `status_kind(status)` → `red|yellow|green`（`build-course-pages.py:327`），检索记录直接复用，不重算。

### 1.2 索引产物 schema（`site/search-index.json`）

构建期生成，UTF-8，`base` 前缀由 `--base` 决定（与页面路由同源，复用 `prefix_path()`）。

```jsonc
{
  "generated_at": "2026-06-30T10:00:00+08:00",   // 构建时间戳，RFC3339，含 +08:00
  "content_revision": "<build HEAD commit>",      // 复用 build() 已采集的 git_head_commit()，与页面一致
  "documents": [
    {
      "kind": "course",                           // "course" | "major"
      "code": "15044",                            // 课程代码 / 专业代码
      "title": "马克思主义基本原理",                // 页面主标题（parse_heading_title）
      "route": "/courses/15044/",                 // 已 base 化的绝对路由（prefix_path）
      "status": "yellow",                         // red | yellow | green（status_kind，见 §1.4）
      "status_label": "🟡 机器初稿",               // 原始状态字面量，前端可直显
      "status_hint": "建设中",                     // 仅 red 时填「建设中」，供前端标注不误导；其余为空串
      "keywords": ["马克思主义基本原理", "15044", "思政"],  // 见 §1.3 关键词口径
      "searchable_text": "马克思主义基本原理 ... 课程重点 ...",  // 见 §1.3，已去 banner/审签噪音
      "credits": "3",                             // 课程：学分；专业：空串
      "level": ""                                 // 专业：层次；课程：空串
    }
  ]
}
```

字段口径：

- `status` 取值严格对应 `status_kind()` 的 `red|yellow|green`，前端按此渲染色点（已有 CSS `.status-dot--red/yellow/green`）。
- `status_hint`：`red` 必填「建设中」（对照父 issue「🔴 占位页可标注建设中不误导」）；`yellow`/`green` 留空串，不空 `null`。
- 大 ID 一律 string（`code` 本就是 string；无数值 ID，规避 JS 精度问题，遵循 [[api-contract-spec]] 字段约定）。
- `generated_at` 用 RFC3339 字符串（全项目时间统一为 RFC3339）。

### 1.3 `keywords` / `searchable_text` 抽取口径

- `keywords`：`title` + `code` + 课程页「适用专业清单」表中的专业名称（专业维度）+（课程）`credits` 文本。不做语义扩写，避免过度工程化。
- `searchable_text`：取课程/专业页面 `body` 经 `strip_review_sections()` 后的可见文本——**剔除** `## 人工审核清单`、`## AI 生成声明`、`## 版本历史` 三段（审签/历史噪音，不应进检索），**保留**正文各区块。大小写折叠 + 全角转半角 + 去多余空白后再存，降低噪音体积。
- 不做分词、不引外部库（红线：不过度工程化）。

### 1.4 检索三态（对照父 issue 验收，映射到 [[api-contract-spec]]）

本站无服务端，故用「客户端三态」等价替换契约的 HTTP 三态：

| 验收态 | 触发 | 行为 | 对应契约语义 |
| --- | --- | --- | --- |
| 正常态 | `fetch` 成功且 `documents.length>0` | 按关键词命中渲染列表，每项带状态色点 + `status_hint` | code=0 |
| 空态 | 命中数为 0 | 友好空结果提示（沿用 `major-search` 文案风格），不报错、不返回脏数据 | code=0 + 空 list |
| 异常态 | `fetch` 失败 / JSON 解析失败 / `documents` 缺失 | **降级为目录浏览**：隐藏检索框或退回 `/courses/` `/majors/` 索引页，顶部提示「检索暂时不可用，请按目录浏览」，不白屏 | 等价 5xxx 服务端内部错误的客户端降级 |

前端实现红线：异常态**不得**把 fetch 失败吞掉后渲染空列表伪装成「无结果」——空态与异常态必须区分提示。

### 1.5 构建落点（实现归属 `scripts/`）

新增函数 `build_search_index(pages, major_rows, result) -> dict`，在 `build()` 渲染完页面后、写 `course-build-report.md` 前调用，落盘 `site/search-index.json`。索引缺失/异常计入 `result.warnings`（非 error，不阻断构建——与现有 majors 缺目录降级为纯文本的容错一致）。

## 2. B-2 内容自动写入管道

### 2.1 实现方向（复用现有四段式，不另起架构）

- 复用 `scripts/process-pdfs.ps1` 四段式流水线：`pdftohtml -xml` → `pdftotext -layout` → 规范化 HTML → Markdown 草稿 + pipeline-notes。**不替换该脚本**，在其下游衔接一个新增的「课程页初稿生成」步骤。
- 新增 `scripts/seed-course-draft.py`（依赖-free，与 `build-course-pages.py` 同风格）：读取专业计划 sources 的 `*.extracted.md`，按课程代码生成/更新 `docs/jiangsu/courses/<code>.md` 的**机器初稿骨架**，并登记来源与时间戳。
- 产物统一进 A 的人工校对队列（见 §4）。

### 2.2 必填区块骨架（课程页初稿，对照 15044 样板）

每页初稿须含以下区块骨架（空源区块写空态占位，见 §2.4）：

1. frontmatter（含 `status: draft`、`version`、`data_status` 三段，见 §2.3）
2. 标题 + 元信息表（省份/课程代码/课程名称/学分/状态=🟡 机器初稿/版本号/数据状态）
3. `> ⚠️ 以下内容为 AI 辅助从官方考纲 PDF 机器抽取生成，尚未经人工校对...` 横幅（**沿用 15044 现行字面量，不新造**）
4. 政策与时效、考纲概览、教材信息、章节知识树、考期索引、新旧课程顶替、来源与引用、相关课程链接、适用专业清单
5. `## AI 生成声明` 表 + 尾部 ⚠️ 横幅（见 §2.5）
6. `## 版本历史`、`## 人工审核清单`

### 2.3 frontmatter 契约（机器初稿强制字段）

```yaml
status: draft          # 机器初稿强制 draft；禁止 published
version: v0.1          # 初稿起步
data_status:
  machine_draft:
    status: generated
    generated_at: "2026-06-30"        # 生成日期 RFC3339 date
    source: "syllabus_pdf"            # syllabus_pdf | textbook_plan_pdf | major_plan_pdf
    source_ref: "docs/jiangsu/source/syllabus/15044.pdf"  # PDF 仓库内路径或官方链接
    blocks:
      completed: 0
      total: 13
      pending: ["政策与时效", "考纲概览", ...]
  human_review:
    status: not_started               # 强制 not_started，机器不写 reviewed/signed
    reviewer: null
    reviewed_at: null
  publish:
    ready: false                      # 强制 false
    blockers:
      - code: human_review_pending
        severity: blocker
        note: 机器初稿，🟢 发布前须逐块人工校对并补签名
```

### 2.4 空态占位（源数据缺失区块）

某区块源缺失时写：

```markdown
## 教材信息

> ⚠️ 待补全：本区块源数据缺失（教材计划未覆盖课程 `<code>`），待人工从官方教材计划核补。

| 字段 | 内容 |
| --- | --- |
| 教材名称 | 待补充 |
| 版本年份 | 待补充 |
```

红线：`待补充`/`待统计`/`待收集`/`待校对` 等占位词直接落地——复用 `build-course-pages.py` 已有的 `decorate_cell()` 占位渲染（`placeholder` class），不虚构内容、**绝不置 🟢**。

### 2.5 AI 生成声明表行（沿用 15044 格式，不新造）

```markdown
## AI 生成声明

| 区块 | 生产方式 | 校对状态 | 校对签名 | 校对日期 |
| --- | --- | --- | --- | --- |
| 考纲概览 | 机器抽取（考纲 §Ⅰ/§Ⅱ/§Ⅲ/§Ⅳ.五/样卷） | ⚠️ 待校对 | 待 Git commit author | 待校对 |
| 教材信息 | 机器抽取（考纲 §Ⅳ.二 + 教材计划） | ⚠️ 待校对 | 待 Git commit author | 待校对 |
| 章节知识树 | 机器抽取（考纲 §Ⅲ 各章考核知识点） | ⚠️ 待校对 | 待 Git commit author | 待校对 |
| （... 其余区块同结构 ...） | | | | |

> 以下内容为 AI 辅助从官方考纲 PDF 机器抽取生成，尚未经人工校对，可能存在错误。发布前须逐区块人工核对并补全校对签名。
```

- 生产方式 = 管道标注的来源段（哪份 PDF 的哪个章节）。
- 校对状态统一 `⚠️ 待校对`；校对签名 = `待 Git commit author`（A 轨道人工校对后由 commit author 落名，可追溯）。

### 2.6 来源与时间戳登记结构

每页 `## 来源与引用` 表强制登记：

| 类别 | 来源 | 状态 |
| --- | --- | --- |
| 考纲（本地） | `docs/jiangsu/source/syllabus/<code>.pdf` | 已归档 |
| 教材计划 | 本地仓库源数据目录（路径不公开） | 已处理 |
| 生成时间 | `2026-06-30T10:00:00+08:00` | 机器登记 |

frontmatter `data_status.machine_draft.source_ref` + `generated_at` + 此表三处一致，构成可追溯三元组。

### 2.7 异常态处理（冲突 / 解析失败）

- 抽取结果与官方计划冲突 → 该页/区块 status 维持 `draft`，frontmatter `publish.blockers` 追加 `{code: extraction_conflict, severity: warning, note: "<冲突描述>"}`，正文对应区块加 `> ⚠️ 待人工核对：<冲突点>`。
- PDF 解析失败 → `seed-course-draft.py` 跳过该页写入，向 stderr 输出清单，并写一份 `docs/jiangsu/source/pipeline-exceptions.md`（追加模式）记录失败课程码 + 失败原因 + 源 PDF。
- **绝不静默覆盖已有人工校对内容**：`seed-course-draft.py` 写入前检测目标 `<code>.md`，若 `frontmatter.human_review.status != not_started` 或 `status` 已为非 draft，则**跳过写入**并在 exceptions 清单登记「已有人工校对，跳过自动覆盖」，不覆盖。

## 3. 质量红线（硬约束，写进实现）

1. 管道**禁止自动置 🟢**：`seed-course-draft.py` 只产出 `status: draft`（🔴→🟡），任何路径不写 `published`/🟢。
2. 🟡→🟢 必须走 A 轨道人工校对签名（frontmatter `reviewed: true` + `reviewer` + Git commit author），管道不触碰该字段。
3. 强制 AI 生成声明（§2.5）+ 页面 ⚠️ 横幅（§2.2 第 3 项）。
4. 可追溯：来源（§2.6）+ 时间戳 + 校对签名追溯 Git commit author。
5. 不过度工程化：不引检索后端/外部依赖；B-2 复用 `process-pdfs.ps1`，不另起架构。

## 4. 产能与交付链路

- A:B SME 时间 = 7:3。`seed-course-draft.py` 默认**单次只处理指定课程码列表**（`--codes 15044,15043`），不默认全量扫，避免一次灌入大量未校对 🟡 饿死 A。全量批处理需显式 `--all` 且在 issue 评论登记批次规模。
- B 产出的机器初稿**统一进 A 的人工校对队列**，不绕过审核对外发布。
- B 的 KPI = 降低 A 单门课填埋成本，非最大化自动写入页数。

## 5. 合规与法务（交付前必带）

- AI 生成声明合规、真题/教材版权 → 测试/部署前**显式 assign 给法务合规团队**终审。
- 真题区块沿用 15044 现行版权口径（不包含第三方原题全文、解题思路描述通用方法论不绑定具体题号），B-2 不新增真题内容，仅复用占位。
- 教材本地路径不公开（沿用 15044「本地电子教材库，路径不公开」）。

## 6. 影响面 / 验证 / 风险（按 [[pr-description-template]]）

### 影响面
- 用户可见变更：课程/专业页顶部新增检索入口；新增机器初稿课程页（🟡）。
- 接口契约变更：无 HTTP 接口；新增静态 `search-index.json` schema（§1.2）+ 课程页 frontmatter 字段（§2.3）。
- 数据库变更：无。
- 性能/兼容性/部署：`search-index.json` 随构建生成进 `site/`（已被 `.gitignore`）；无新增运行时依赖。CI（`deploy-pages.yml`）无需改。

### 验证
- [ ] B-1：`python scripts/build-course-pages.py --base /jiangsu-zikao-aio/` 后 `site/search-index.json` 存在且 `documents` 非空、每项含 `status`。
- [ ] B-1 三态：正常命中 / 空态文案 / fetch 失败降级目录浏览（断网或删索引文件复现）。
- [ ] B-2：`seed-course-draft.py --codes <x>` 生成 `<x>.md`，frontmatter `status=draft`、含 AI 生成声明表 + ⚠️ 横幅 + 来源登记。
- [ ] B-2 空态：源缺失区块写 `待补充` 占位，不置 🟢。
- [ ] B-2 异常：人为制造 PDF 解析失败 → 写 `pipeline-exceptions.md`，不覆盖已校对页。

### 风险与回滚
- 已知风险：`searchable_text` 体积随课程页增长；初版可接受，后续需评估分片（属非本期）。
- 回滚：B-1 删除 `build_search_index` 调用即恢复；B-2 初稿是 `docs/` 下 Git 受控文件，`git revert` 即回滚，无迁移需回退。

## 7. 待确认问题

1. 检索入口放置位置（顶部导航全局 vs 仅 `/courses/` `/majors/` 索引页）——建议本期先放索引页，全局检索待 IA 选型确认后另起切片（IA.md §6「本期不改路由结构」）。
2. `seed-course-draft.py` 的 `--all` 全量批处理首批规模上限——待与 A 轨道对齐 7:3 产能后定。

