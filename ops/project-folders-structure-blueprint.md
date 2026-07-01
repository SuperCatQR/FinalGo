# Project Folders Structure Blueprint

最后更新：2026-06-24（全面重构）

## 结构原则

按“语义分层”组织仓库，而不是把内容、原始数据和工作流文档混在同一棵目录里。

- `content/` = 会被构建器渲染并进入 `site/` 的 Markdown 发布内容。
- `sources/` = 原始 PDF、机器抽取产物、批处理清单、真题原件——不进入 `site/`。
- `ops/` = 政策、工作流、闸门契约、模板、外链基线等元文档，供内容作者查阅，不进入 `site/`。
- `scripts/` = Python/PowerShell 脚本。
- `archive/` = 历史阶段留档，不参与发布。
- `build.toml` = 路径 + 巡检配置；构建脚本从这里读，改目录不需要改代码。

省份是一等公民：`content/jiangsu/`、`sources/jiangsu/`、`ops/jiangsu/` 三条支线独立存在。追加浙江/安徽时新建 `content/zhejiang/` 等同层目录，不用重排现有内容。

## 当前结构

```text
jiangsu-zikao-aio/
├── README.md                                    # 项目入口
├── GIT_GUIDE.md                                 # 分支/提交规范
├── build.toml                                   # 构建 + 外链巡检路径配置
├── reasonix.toml                                # 本地 agent 配置
├── .gitignore                                   # 忽略 site/、agent runtime、CLAUDE.md/AGENTS.md
├── .github/workflows/
│   ├── deploy-pages.yml                         # Pages 部署 + Lighthouse/axe 巡检
│   └── source-link-monitor.yml                  # 外链可达性巡检
├── content/
│   └── jiangsu/                                 # 江苏发布内容
│       ├── index.md                             # 江苏资料入口
│       ├── majors/                              # 54 个专业工作区 + index.md
│       │   └── <专业代码>-<英文slug>/
│       │       ├── index.md
│       │       ├── sources.md
│       │       └── sources/                     # 专业内部抽取产物（plan.raw.*、plan.extracted.md）
│       └── courses/                             # 跨专业课程页
│           ├── index.md                         # 课程索引源
│           └── <5位课程代码>/index.md            # 统一课程页形态
├── sources/
│   └── jiangsu/                                 # 江苏原始与处理产物
│       ├── *.pdf                                # 省级共享 PDF（政策/目录/教材计划）
│       ├── major-plans-2024/                    # 54 个专业计划 PDF（原“2.江苏省…”目录）
│       ├── syllabus/*.pdf                       # 官方独立考纲 PDF
│       ├── textbooks/*.pdf                      # 每次考试教材计划 PDF
│       ├── past-papers/                         # 官方公开真题
│       ├── pdf-processing-manifest.csv          # PDF 处理清单
│       ├── pdf-processing-report.md             # PDF 处理报告
│       └── processed/
│           ├── documents/                       # 共享 PDF 的规范化/抽取产物
│           ├── syllabus/                        # 官方考纲的规范化/抽取产物
│           └── textbooks/                       # 教材计划的规范化/抽取产物
├── ops/
│   ├── project-folders-structure-blueprint.md   # 本文件
│   └── jiangsu/
│       ├── policies.md                          # 江苏省政策口径
│       ├── workflow.md                          # 专业页批量生产工作流
│       ├── pdf-to-markdown-pipeline.md          # PDF 四段式流水线设计
│       ├── publish-gate-contract.md             # 发布闸门 B-1/B-2/B-3 契约
│       ├── course-review-checklist.md           # 课程页人工审核清单
│       ├── source-link-monitor.md               # 外链监控说明
│       ├── source-links.baseline.json           # 外链监控基线
│       └── templates/
│           ├── major.md
│           ├── course.md
│           └── course-review-checklist.md
├── scripts/
│   ├── build-course-pages.py                    # 站点生成器 + 发布闸门（读 build.toml）
│   ├── check-source-links.py                    # 外链巡检（读 build.toml）
│   ├── process-pdfs.ps1                         # PDF 批处理（PowerShell）
│   └── templates/                               # 站点渲染用 CSS 模板
│       ├── base.css
│       └── theme.css
├── archive/                                     # 历史存档，不参与发布
│   ├── README.md
│   └── design-proposals/                        # CHO-94 设计选型 4 套原型 + track-b 契约初稿
└── site/                                        # 构建产物（.gitignore）
```

## build.toml

路径都在这里。修改后不必碰 Python 脚本。

```toml
[paths]
courses_dir     = "content/jiangsu/courses"
majors_dir      = "content/jiangsu/majors"
templates_dir   = "scripts/templates"
out_dir         = "site/courses"
site_dir        = "site"

[source_link_monitor]
baseline        = "ops/jiangsu/source-links.baseline.json"
report          = "site/source-link-report.md"
summary         = "site/source-link-report.json"
```

未指定的字段回落到脚本内 defaults。

## 目录职责

| 路径 | 用途 |
| --- | --- |
| `README.md` | 项目入口 |
| `build.toml` | 构建 + 巡检路径配置 |
| `content/jiangsu/index.md` | 江苏资料入口 |
| `content/jiangsu/majors/<major>/index.md` | 单专业主页 |
| `content/jiangsu/majors/<major>/sources.md` | 单专业资料源清单 |
| `content/jiangsu/majors/<major>/sources/` | 专业专用抽取产物 |
| `content/jiangsu/courses/<code>/index.md` | 统一课程页 |
| `content/jiangsu/courses/index.md` | 课程索引源（只被 render_index 消费） |
| `sources/jiangsu/*.pdf` | 省级官方原始 PDF |
| `sources/jiangsu/major-plans-2024/` | 54 个专业计划 PDF（一次性大包） |
| `sources/jiangsu/syllabus/` | 官方独立考纲原件 |
| `sources/jiangsu/textbooks/` | 教材计划原件 |
| `sources/jiangsu/past-papers/` | 官方公开真题 |
| `sources/jiangsu/processed/` | 机器处理产物 |
| `sources/jiangsu/pdf-processing-manifest.csv` | PDF 处理清单 |
| `sources/jiangsu/pdf-processing-report.md` | PDF 处理报告 |
| `ops/jiangsu/policies.md` | 江苏省级政策口径 |
| `ops/jiangsu/workflow.md` | 专业页批量生产工作流 |
| `ops/jiangsu/pdf-to-markdown-pipeline.md` | PDF 四段式流水线设计 |
| `ops/jiangsu/publish-gate-contract.md` | 发布闸门契约 |
| `ops/jiangsu/course-review-checklist.md` | 课程页发布前审核清单 |
| `ops/jiangsu/source-link-monitor.md` | 外链监控说明 |
| `ops/jiangsu/source-links.baseline.json` | 外链监控基线 |
| `ops/jiangsu/templates/` | 专业/课程页模板 |
| `scripts/build-course-pages.py` | 站点生成器；从 `build.toml` 读路径 |
| `scripts/check-source-links.py` | 外链巡检；从 `build.toml [source_link_monitor]` 读配置 |
| `scripts/process-pdfs.ps1` | PDF 批处理（PowerShell） |
| `scripts/templates/` | 站点 CSS 模板 |
| `archive/` | 项目内历史存档，不参与发布 |
| `C:\WorkSpace\project\FinalGo_local_archive\` | 项目外本地归档 |

## Major 工作区模板

新增专业时：

```text
content/jiangsu/majors/<专业代码>-<english-slug>/
├── index.md
├── sources.md
└── sources/
    ├── plan.raw.xml
    ├── plan.raw.txt
    ├── plan.normalized.html
    ├── plan.extracted.md
    └── plan.pipeline-notes.md
```

`index.md` 面向阅读和发布，`sources.md` 面向可追溯审核，`sources/` 放机器抽取产物。命名示例：

```text
content/jiangsu/majors/080901-computer-science-and-technology/
```

## 课程页统一形态

所有课程页统一放在：

```text
content/jiangsu/courses/<5位课程代码>/index.md
```

`content/jiangsu/courses/index.md` 只作为课程索引源，不渲染为课程详情页。

## 相对路径约定

内容间跨目录引用，一律使用相对路径；跨大分区（content → sources / ops）使用相对到仓库根的完整路径写明来源。

- 专业页链共享课程页：`../../courses/<code>/index.md`
- 专业 index/sources 引用原始 PDF：`sources/jiangsu/<pdf-name>.pdf` 或 `sources/jiangsu/processed/<...>/document.extracted.md`
- 专业内部抽取产物：`./sources/plan.raw.xml`
- content → ops 元文档：`../../ops/jiangsu/<name>.md`

理由：让内容作者一眼看出“这条链跳出了 content 分区”，避免误改。

## 放置边界

- 官方考纲、官方公开真题：`sources/jiangsu/{syllabus,past-papers}/` + 走 PDF 流水线处理。
- 教材电子书、第三方题库解析、盗版扫描件：不进入项目树；放 `C:\WorkSpace\project\FinalGo_local_archive\`，仅在公开文档记录 ISBN / 出版社 / 官方教材计划入口。
- 阶段性完成、但不参与发布的原型/契约：`archive/`；不要留在根目录。
- 站点构建产物：`site/`（已 gitignore）。
- Agent runtime（CLAUDE.md / AGENTS.md / .multica/ / .reasonix/ 等）：`.gitignore`，不入库。

## 后续扩展规则

1. 新增专业先建 major 工作区，再写 `index.md`。
2. 先收官方专业计划 PDF/XML/TXT，再填课程表。
3. 公共课只建一份课程页，多个专业链接同一个 `content/jiangsu/courses/<code>/index.md`。
4. 能跨专业复用的教材计划、政策文件放 `sources/<省>/`，不要复制到每个 major。
5. 官方考纲、官方真题入 `sources/<省>/{syllabus,past-papers}/`；第三方解析和教材全文放项目外本地归档。
6. 新增省份：`content/<省>/`、`sources/<省>/`、`ops/<省>/` 三条支线一起加；构建器目前只跑 `content/jiangsu`，多省份要开构建器多路遍历。

## 已清理项

- 2026-06-24 全面重构：
  - `docs/jiangsu` 三分：`content/jiangsu/{majors,courses,index}`、`sources/jiangsu/**`、`ops/jiangsu/**`。
  - 元文档从 docs 抽到 `ops/`；蓝图从 `docs/` 迁到 `ops/project-folders-structure-blueprint.md`。
  - 长中文目录 `2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）` 更名为 `sources/jiangsu/major-plans-2024`。
  - 新增 `build.toml`；`build-course-pages.py` / `check-source-links.py` 从配置读路径，不再硬编码。
  - 内容内 300+ 处相对路径批量修正为新层级。
- 2026-06-23：新增根 `README.md`；`design-proposals/` 归档到 `archive/design-proposals/`；`CLAUDE.md`、`AGENTS.md` 加入 `.gitignore`。
- 将专业页统一为 `majors/<major>/index.md` 目录形态。
- 将计算机科学与技术的 XML/TXT 抽取结果迁入该专业 `sources/`，并统一命名为 `plan.raw.*`。
- 已用 `scripts/process-pdfs.ps1` 批处理 70 个 PDF，其中 54 个专业计划进入各专业目录，16 个共享 PDF 进入 `sources/jiangsu/processed/`。
- 2026-06-22 为 080901 增量下载并处理 7 个官方独立考纲 PDF。
- 将教材 PDF 从项目树移到 `C:\WorkSpace\project\FinalGo_local_archive\e-books\jiangsu\`。
- 将已解压的官方专业计划 RAR 从项目树移到 `C:\WorkSpace\project\FinalGo_local_archive\official-packages\jiangsu\`。
- 清理根目录残留的 UnRAR 辅助文件。
- 删除 Playwright 临时日志目录 `.playwright-cli/`。

维护本蓝图时，优先记录“为什么放这里”，其次再记录“文件叫什么”。
