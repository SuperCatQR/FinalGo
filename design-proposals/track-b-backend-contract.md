# 轨道 B 后端交付包 — 实现方向 + 接口/数据契约

> 对应 issue CHO-107（父 CHO-105）。本文档由后端整合产出，作为前端对接与后端审查的唯一基准。
> 范围：B-1 站内静态全文检索 + B-2 PDF→课程页机器初稿写入管道。
> **本期不改路由结构、不引入检索后端/外部依赖、不新增持久化层。**

> **修订记录（v2，回应后端审查 + PR审查团队终审分诊）**
> - **[阻塞已闭环] §2.7/§2.8**：覆盖保护原仅判嵌套 `human_review.status`，漏判门禁实际强制的扁平 `reviewed`（15043 现状用扁平、15044 用嵌套，两套并存）。已新增 §2.8 裁定单一发布权威字段（扁平 `reviewed: true`+`reviewer`）并把覆盖保护改为**四信号取并集**，消除覆盖窗口；§3 红线 + §6 验证同步补四例并集测试。
> - **[纠错已修] §1.3**：`REVIEW_SECTION_TITLES` 实为 2 段，`版本历史` 不在其中、会漏进 `searchable_text`；已改为「本期把 `版本历史` 一并剔除」并指明实现落点。
> - **[建议已对齐] §2.2**：区块清单补齐至 15044 现行 13 区块，并标注高频概念表/题型与答题模板/真题解析三块本期不机器生成、写空态占位。
> - **[建议已对齐] §1.2/§1.1**：`status` 入参口径更正为 `page.meta["状态"]`（非 frontmatter `status`）；`major-search` 先例措辞更正为 `render_majors_index()` 构建期注入。

## 0. 关键结论（先读）

- **无 HTTP API、无数据库**。本站是 Git 为数据源、`scripts/build-course-pages.py` 生成静态 HTML 的静态站。B-1 检索是「构建期产出静态索引 JSON + 浏览器端纯 JS 过滤」，B-2 写入是「脚本产出 `docs/` 下 Markdown 初稿」。因此 [[api-contract-spec]] 的 HTTP 统一信封 / 错误码段位 / 鉴权**不适用**——没有服务端就没有这些层。本文用「静态产物 schema + 客户端降级三态」替代，下文 §1.4 显式做映射。
- **无 Schema 变更 → 不走 DBA。** 索引产物是构建副产物（写进 `site/`，已被 `.gitignore` 忽略，随构建再生）；初稿产物是 `docs/` 下的 Markdown 文本，归 Git 版本管理。两者都不引入数据库或持久化结构。若后续审查认为需要独立索引服务/DB，属另起切片，按 [[db-migration-safe]] 提 DBA，本期不做。
- **合规前置**：AI 生成声明机制、真题/教材版权 → 交付测试/部署前**必须显式带上法务合规团队**终审（见 §5）。

## 1. B-1 站内全文检索

### 1.1 实现方向

- 在 `scripts/build-course-pages.py` 的 `build()` 末尾新增一步，遍历已加载的 `pages`（课程）与 `major_rows`（专业），产出单个静态文件 `site/search-index.json`。
- 前端检索 UI = 纯 vanilla JS：`fetch('search-index.json')` → 内存过滤 → 渲染结果列表。**复用现有先例**：专业索引页的即时过滤 JS 由 `build-course-pages.py:1033` `render_majors_index()` 在构建期注入 HTML（`major-search-input`，含空态文案「未找到匹配专业，请尝试其他关键词」逐字属实），B-1 把同样的模式从「单页表格过滤」升级为「跨页 JSON 索引过滤」，不新造机制。
- 状态来源：构建脚本已有 `status_kind(status)` → `red|yellow|green`（`build-course-pages.py:327`），检索记录直接复用同一函数，不重算（注意其入参口径见 §1.4）。

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

- `status` 取值严格对应 `status_kind()` 的 `red|yellow|green`，前端按此渲染色点（已有 CSS `.status-dot--red/yellow/green`）。**入参口径核实**：`status_kind()`（`build-course-pages.py:327`）按 emoji 前缀（🔴/🟡/🟢）判定，且 `status_banner()`（line 339）传入的是**元信息表 `状态` 单元格**（`page.meta.get("状态")`），**不是** frontmatter 顶层 `status`（其值为 `draft`）。索引构建必须复用同一入参——取 `page.meta["状态"]` 喂 `status_kind()`，不可误用 frontmatter `status`，否则全部落 `red`。
- `status_hint`：`red` 必填「建设中」（对照父 issue「🔴 占位页可标注建设中不误导」）；`yellow`/`green` 留空串，不空 `null`。
- 大 ID 一律 string（`code` 本就是 string；无数值 ID，规避 JS 精度问题，遵循 [[api-contract-spec]] 字段约定）。
- `generated_at` 用 RFC3339 字符串（全项目时间统一为 RFC3339）。

### 1.3 `keywords` / `searchable_text` 抽取口径

- `keywords`：`title` + `code` + 课程页「适用专业清单」表中的专业名称（专业维度）+（课程）`credits` 文本。不做语义扩写，避免过度工程化。
- `searchable_text`：取课程/专业页面 `body` 经 `strip_review_sections()` 后的可见文本。**现状核实**：`build-course-pages.py:683` 的 `REVIEW_SECTION_TITLES` 仅剔除 **2 段**——`## 人工审核清单` 与 `## AI 生成声明`（审签噪音）；`## 版本历史` **当前不在剔除列表内，会进入 `searchable_text`**。本期口径决定：**把 `版本历史` 一并视为非检索噪音剔除**，实现归属在 `build_search_index` 调用前把 `"版本历史"` 加入 `REVIEW_SECTION_TITLES`（或对索引用一份含三段的剔除集），使契约「剔 3 段」与实现一致。大小写折叠 + 全角转半角 + 去多余空白后再存，降低噪音体积。
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
4. 正文区块骨架——**对齐 15044 现行 13 区块**（已核实 15044 H2 区块）：政策与时效、考纲概览、教材信息、章节知识树、**高频概念表**、**题型与答题模板**、**真题解析**、考期索引、新旧课程顶替、来源与引用、相关课程链接、适用专业清单（机器初稿可生成的与需人工后补的标注见下）。
   - **本期 B-2 机器初稿生成范围**：可从考纲 PDF 机器抽取的区块（政策与时效、考纲概览、教材信息、章节知识树、考期索引、新旧课程顶替、来源与引用、相关课程链接、适用专业清单）产出 🟡 初稿骨架；**`高频概念表` / `题型与答题模板` / `真题解析` 三块本期不机器生成**（依赖真题原件与教研加工，超出考纲 PDF 可抽取范围），统一写空态占位（见 §2.4）+ 待办，留给 A 轨道人工补全，**绝不虚构**。
5. `## AI 生成声明` 表 + 尾部 ⚠️ 横幅（见 §2.5）
6. `## 版本历史`、`## 人工审核清单`

### 2.3 frontmatter 契约（机器初稿强制字段）

```yaml
status: draft          # 机器初稿强制 draft；禁止 published
version: v0.1          # 初稿起步
# 扁平人工校对权威键：机器初稿强制 reviewed: false + reviewer 为空。
# 这是 🟢 发布门禁 (_check_human_review, build-course-pages.py:498) 认的唯一权威字段
# (见 §2.8)。管道只写 false，绝不写 true。
reviewed: false
reviewer: ""
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
    status: not_started               # 描述性进度元数据，非发布权威字段（见 §2.8）
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
- **绝不静默覆盖已有人工校对内容**（红线，闭环口径见 §2.8）：`seed-course-draft.py` 写入前检测目标 `<code>.md`，命中**任一**人工介入信号即**跳过写入**并在 exceptions 清单登记「已有人工校对/人工介入，跳过自动覆盖」，绝不覆盖。

### 2.8 「已人工校对」权威字段与覆盖保护口径（红线闭环）

**问题背景**：仓库现存两套人工校对表示并存，不可只判其一：
- **扁平键** `reviewed: true` + `reviewer`（15043 现状 `reviewed: false`）——这是 `build-course-pages.py:498` `_check_human_review()` 实际强制的 **🟢 发布门禁权威字段**。
- **嵌套键** `data_status.human_review.status`(15044 现状 `not_started`)+ `reviewer` / `reviewed_at`——管道写入的进度元数据。

**权威字段裁定（单一权威 + 描述性元数据)**：
- **🟢 可发布的唯一权威判定 = 扁平 `reviewed: true` 且 `reviewer` 非空**(沿用既有门禁 `_check_human_review`,不新造、不改门禁语义)。A 轨道人工校对签名落 `reviewed: true` + `reviewer`,追溯至 Git commit author。
- 嵌套 `data_status.human_review.*` 为**描述性进度元数据**(已校对几块/校对时间),管道可写、门禁不读;它**不是**发布权威字段。A 轨道翻 🟢 时应同时维护两者,但门禁只认扁平 `reviewed`。

**覆盖保护(管道写入前,口径取并集 = 最保守)**:`seed-course-draft.py` 命中以下**任一**条件即判定「人工已介入」,跳过覆盖:
1. 扁平 `reviewed` ∈ {`true`,`yes`}(真值,大小写不敏感);**或**
2. `reviewer` 字段非空(已有签名人);**或**
3. 嵌套 `data_status.human_review.status` 存在且 ≠ `not_started`;**或**
4. 顶层 `status` 已为非 `draft`(已脱离机器初稿态)。

取并集而非单一字段,消除「A 已设 `reviewed: true` 但未动嵌套字段」或反之的覆盖窗口——任一信号亮起即不覆盖,红线无残留窗口。跳过时写 `pipeline-exceptions.md` 登记课程码 + 命中的信号 + 时间戳。

> 后续优化(非本期,转 issue 跟进):A 轨道校对流程统一为「翻 🟢 时同步扁平 `reviewed` 与嵌套 `human_review.status=done`」,使两套表示恒一致;本期靠覆盖保护取并集兜底,不要求 Schema 迁移。

## 3. 质量红线（硬约束，写进实现）

1. 管道**禁止自动置 🟢**：`seed-course-draft.py` 只产出 `status: draft` + `reviewed: false`（🔴→🟡），任何路径不写 `published`/🟢、不写 `reviewed: true`。
2. 🟡→🟢 必须走 A 轨道人工校对签名（权威字段 = 扁平 `reviewed: true` + `reviewer` + Git commit author，见 §2.8），管道不触碰该权威字段。
3. **绝不静默覆盖已校对**：覆盖保护按 §2.8 取并集（扁平 `reviewed`/`reviewer`、嵌套 `human_review.status`、顶层 `status` 任一亮起即跳过），消除单字段判定的覆盖窗口。
4. 强制 AI 生成声明（§2.5）+ 页面 ⚠️ 横幅（§2.2 第 3 项）。
5. 可追溯：来源（§2.6）+ 时间戳 + 校对签名追溯 Git commit author。
6. 不过度工程化：不引检索后端/外部依赖；B-2 复用 `process-pdfs.ps1`，不另起架构。

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
- [ ] B-1 `status` 入参：索引项 `status` 由 `page.meta["状态"]` 喂 `status_kind()` 得出（15044 应为 `yellow`，非全 `red`），未误用 frontmatter `status`（§1.2）。
- [ ] B-1 `searchable_text`：不含 `## 人工审核清单` / `## AI 生成声明` / `## 版本历史` 三段文本（§1.3，确认 `版本历史` 已剔除）。
- [ ] B-1 三态：正常命中 / 空态文案 / fetch 失败降级目录浏览（断网或删索引文件复现）。
- [ ] B-2：`seed-course-draft.py --codes <x>` 生成 `<x>.md`，frontmatter `status=draft` + `reviewed=false`、含 AI 生成声明表 + ⚠️ 横幅 + 来源登记。
- [ ] B-2 空态：源缺失区块写 `待补充` 占位，不置 🟢；高频概念表/题型与答题模板/真题解析三块本期写空态占位不机器生成（§2.2）。
- [ ] B-2 覆盖保护并集（§2.8，红线闭环）：分别构造四种已介入页各跑一次管道，均跳过且登记到 `pipeline-exceptions.md`——(a) 仅扁平 `reviewed: true`（嵌套仍 `not_started`）；(b) 仅 `reviewer` 非空；(c) 仅嵌套 `human_review.status != not_started`；(d) 仅顶层 `status` 非 draft。四例任一被覆盖即视为红线未闭环。
- [ ] B-2 异常：人为制造 PDF 解析失败 → 写 `pipeline-exceptions.md`，不覆盖已校对页。

### 风险与回滚
- 已知风险：`searchable_text` 体积随课程页增长；初版可接受，后续需评估分片（属非本期）。
- 回滚：B-1 删除 `build_search_index` 调用即恢复；B-2 初稿是 `docs/` 下 Git 受控文件，`git revert` 即回滚，无迁移需回退。

## 7. 待确认问题

1. 检索入口放置位置（顶部导航全局 vs 仅 `/courses/` `/majors/` 索引页）——建议本期先放索引页，全局检索待 IA 选型确认后另起切片（IA.md §6「本期不改路由结构」）。
2. `seed-course-draft.py` 的 `--all` 全量批处理首批规模上限——待与 A 轨道对齐 7:3 产能后定。

