# Project Folders Structure Blueprint

最后更新：2026-06-21

## 结构原则

本项目是自考资料文档库，当前以江苏省资料为主。目录按“省份共享资料 + 专业工作区 + 共享课程页”组织，而不是单纯按文件类型堆放。

推进某个专业时，例如“计算机科学与技术”，新增和校对工作优先落在该专业自己的 `majors/<major>/` 目录中；跨专业复用的政策、教材计划和课程页仍放在省级共享层。

## 当前结构

```text
FinalGo/
├── docs/
│   ├── Project_Folders_Structure_Blueprint.md
│   └── jiangsu/
│       ├── index.md
│       ├── policies.md
│       ├── workflow.md
│       ├── pdf-to-markdown-pipeline.md
│       ├── templates/
│       │   └── major.md
│       ├── majors/
│       │   ├── index.md
│       │   ├── 030101K-law/
│       │   │   └── index.md
│       │   ├── 050101-chinese-language-literature/
│       │   │   └── index.md
│       │   ├── 080901-computer-science-and-technology/
│       │   │   ├── index.md
│       │   │   ├── sources.md
│       │   │   └── sources/
│       │   │       ├── plan.raw.txt
│       │   │       ├── plan.raw.xml
│       │   │       ├── plan.normalized.html
│       │   │       └── plan.extracted.md
│       │   └── 120203K-accounting/
│       │       └── index.md
│       ├── courses/
│       └── source/
│           ├── pdf-processing-manifest.csv
│           ├── pdf-processing-report.md
│           ├── processed/
│           ├── syllabus/
│           ├── past-papers/
│           ├── textbooks/
│           ├── 2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）/
│           └── *.pdf / *.txt
├── scripts/
│   └── process-pdfs.ps1
└── reasonix.toml
```

## 目录职责

| 路径 | 用途 | 放置规则 |
| --- | --- | --- |
| `docs/jiangsu/index.md` | 江苏资料入口 | 只放导航、当前口径和核心待办 |
| `docs/jiangsu/policies.md` | 江苏省级政策口径 | 放跨专业、跨课程共用的政策解释 |
| `docs/jiangsu/workflow.md` | 专业页生产流程 | 放 PDF 转换、字段抽取、审核关卡和自动化建议 |
| `docs/jiangsu/pdf-to-markdown-pipeline.md` | PDF 转 Markdown 流水线设计 | 放四段式转换方案、产物命名和验收点 |
| `docs/jiangsu/templates/` | 文档模板 | 放新专业、新课程等可复制模板 |
| `docs/jiangsu/majors/<major>/index.md` | 单专业主页 | 放专业基本信息、课程表、毕业要求、建设路线 |
| `docs/jiangsu/majors/<major>/sources.md` | 单专业资料源清单 | 放本专业教材、大纲、真题线索和审核边界 |
| `docs/jiangsu/majors/<major>/sources/` | 单专业抽取产物 | 放该专业 PDF 转 XML/TXT 的中间产物 |
| `docs/jiangsu/source/processed/` | 共享 PDF 处理产物 | 放省级目录、政策简编、教材计划等非单专业 PDF 的 raw/HTML/Markdown 产物 |
| `docs/jiangsu/source/syllabus/` | 官方考试大纲原件 | 放江苏省教育考试院、主考学校公开发布的考纲 PDF |
| `docs/jiangsu/source/past-papers/` | 官方真题原件或真题元数据 | 官方公开真题可按课程/考期入库；第三方题库和解析不放发布树 |
| `docs/jiangsu/source/pdf-processing-manifest.csv` | PDF 处理清单 | 记录所有 PDF 输入、输出目录和产物路径 |
| `docs/jiangsu/source/pdf-processing-report.md` | PDF 处理报告 | 记录批处理时间、数量和当前数据状态 |
| `docs/jiangsu/courses/` | 跨专业课程页 | 以课程代码命名，例如 `13003.md` |
| `docs/jiangsu/source/` | 省级官方原始资料 | 放官方 PDF、教材计划 XML/TXT 等共享来源 |
| `scripts/process-pdfs.ps1` | PDF 批处理脚本 | 批量生成 raw XML/TXT、规范化 HTML、Markdown 草稿和转换记录 |
| `C:\WorkSpace\project\FinalGo_local_archive\` | 项目外本地归档 | 放不适合发布或不需要长期留在项目树内的大体积资料 |

## Major 工作区模板

新增专业时使用：

```text
docs/jiangsu/majors/<专业代码>-<english-slug>/
├── index.md
├── sources.md
└── sources/
    ├── plan.raw.xml
    ├── plan.raw.txt
    ├── plan.normalized.html
    ├── plan.extracted.md
    └── plan.pipeline-notes.md
```

命名示例：

```text
docs/jiangsu/majors/080901-computer-science-and-technology/
```

`index.md` 面向阅读和发布，`sources.md` 面向可追溯审核，`sources/` 面向机器抽取、规范化和人工复核。

## 文件放置约定

专业页内链接共享课程页时，从 `index.md` 使用：

```text
../../courses/<课程代码>.md
```

专业页引用省级官方资料时，从 `index.md` 使用：

```markdown
`../../source/jiangsu-plan-handbook-2024.pdf`
```

专业专用抽取文件不再放 `source/html/`，统一放：

```text
docs/jiangsu/majors/<major>/sources/plan.raw.xml
docs/jiangsu/majors/<major>/sources/plan.raw.txt
docs/jiangsu/majors/<major>/sources/plan.normalized.html
docs/jiangsu/majors/<major>/sources/plan.extracted.md
```

官方考试大纲和官方公开真题可以进入 `docs/jiangsu/source/` 并走 PDF 流水线处理。教材电子书、扫描件、第三方题库解析、网盘资料等不进入 `docs/` 发布树。若暂时保留用于人工核对，放入项目外本地归档 `C:\WorkSpace\project\FinalGo_local_archive\`，并在公开文档里只记录来源、ISBN、出版社、官方教材计划或线索入口。

## 后续扩展规则

1. 新增专业先建 major 工作区，再写 `index.md`。
2. 先收官方专业计划 PDF/XML/TXT，再填课程表。
3. 公共课只建一份课程页，多个专业链接同一个 `courses/<课程代码>.md`。
4. 专业特有实践、毕业设计、主考学校公告放在专业目录下，不放共享课程页。
5. 能跨专业复用的教材计划、政策文件和目录文件放 `source/`，不要复制到每个 major。
6. 官方考纲、官方真题可入 `source/syllabus/`、`source/past-papers/`；第三方解析和教材全文放项目外本地归档，不要从 `docs/` 链接。

## 已清理项

- 将专业页统一为 `majors/<major>/index.md` 目录形态。
- 将计算机科学与技术的 XML/TXT 抽取结果迁入该专业 `sources/`，并统一命名为 `plan.raw.*`。
- 已用 `scripts/process-pdfs.ps1` 批处理 70 个 PDF，其中 54 个专业计划进入各专业目录，16 个共享 PDF 进入 `source/processed/`。
- 2026-06-22 为 080901 增量下载并处理 7 个官方独立考纲 PDF，当前 manifest 共 70 条记录。
- 将教材 PDF 从项目树移到 `C:\WorkSpace\project\FinalGo_local_archive\e-books\jiangsu\`。
- 将已解压的官方专业计划 RAR 从项目树移到 `C:\WorkSpace\project\FinalGo_local_archive\official-packages\jiangsu\`，项目内保留 54 个单专业 PDF。
- 清理根目录残留的 UnRAR 辅助文件。
- 删除 Playwright 临时日志目录 `.playwright-cli/`。

维护本蓝图时，优先记录“为什么放这里”，其次再记录“文件叫什么”。目录结构的目标是让每个 major 可以独立推进，同时保证公共来源和课程资产不重复。
