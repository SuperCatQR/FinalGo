# 江苏自考专业页批量生产工作流

目标：把江苏省教育考试院发布的专业考试计划 PDF，稳定转换为可审核、可发布的 Markdown 专业页。优先保证官方来源可追溯和人工审核边界清楚。

本项目采用四段式流水线：

```text
PDF -> 原始 HTML/XML -> 规范化 HTML -> Markdown
```

详细设计见：[PDF 到 Markdown 四段式流水线](./pdf-to-markdown-pipeline.md)。

## 0. 输入与输出

### 输入

- 官方公告页：江苏省教育考试院《 关于江苏省高等教育自学考试面向社会开考专业及考试计划调整有关事项的通告》
- 解压后的单专业 PDF：`source/2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）/*.pdf`
- 官方附件原始 RAR：项目外本地归档 `C:\WorkSpace\project\FinalGo_local_archive\official-packages\jiangsu\jiangsu-major-plans-2024.rar`
- 总览政策：`policies.md`
- 专业页模板：`templates/major.md`

### 输出

- 单专业原始 XML：`majors/<专业代码>-<english-slug>/sources/plan.raw.xml`
- 单专业原始文本：`majors/<专业代码>-<english-slug>/sources/plan.raw.txt`
- 单专业规范化 HTML：`majors/<专业代码>-<english-slug>/sources/plan.normalized.html`
- 单专业 Markdown 草稿：`majors/<专业代码>-<english-slug>/sources/plan.extracted.md`
- 单专业 Markdown：`majors/<专业代码>-<english-slug>/index.md`
- 单专业资料源清单：`majors/<专业代码>-<english-slug>/sources.md`
- 必要时新增课程页：`courses/<课程代码>.md`

## 1. 环境依赖

推荐使用 Poppler 的 `pdftohtml`，因为它比 `pdftotext` 更好地保留中文课名、表格单元格和坐标。

Windows 可用 `winget` 安装：

```bash
winget install --id oschwartz10612.Poppler --accept-package-agreements --accept-source-agreements --silent
```

当前机器安装后的可执行文件位置示例：

```bash
$LOCALAPPDATA/Microsoft/WinGet/Packages/oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe/poppler-25.07.0/Library/bin/pdftohtml.exe
```

跨平台环境如果 `pdftohtml` 已在 `PATH` 中，直接使用 `pdftohtml` 即可。

## 2. PDF 转 XML

以《计算机科学与技术专业（专升本）》为例：

```bash
mkdir -p docs/jiangsu/majors/080901-computer-science-and-technology/sources

POPPLER_BIN="$LOCALAPPDATA/Microsoft/WinGet/Packages/oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe/poppler-25.07.0/Library/bin"

"$POPPLER_BIN/pdftohtml.exe" \
  -xml \
  -i \
  -noframes \
  "docs/jiangsu/source/2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）/26.计算机科学与技术专业（专升本）考试计划.pdf" \
  "docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.raw"
```

输出文件：

```text
docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.raw.xml
```

参数说明：

- `-xml`：输出带坐标的 XML，适合表格抽取和人工复核。
- `-i`：忽略图片，减小输出噪声。
- `-noframes`：生成单文件结构，便于保存和读取。

同时建议生成原始文本：

```bash
pdftotext -layout \
  "docs/jiangsu/source/2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）/26.计算机科学与技术专业（专升本）考试计划.pdf" \
  "docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.raw.txt"
```

## 3. 从原始 XML 生成规范化 HTML

把 `plan.raw.xml` 中的坐标文本整理为 `plan.normalized.html`。规范化 HTML 使用真实标题、段落和表格表达结构，不追求还原 PDF 视觉样式。

关键规则：

1. 专业计划用 `article` 包裹。
2. 稳定章节用 `section[data-section]` 标记。
3. 课程清单必须整理为真实 `table`。
4. 每个来自 PDF 的段落或表格行尽量保留 `data-source-page`。
5. 自动推断字段用 `data-derived="true"` 标记。

## 4. 从规范化 HTML 抽取专业信息

优先抽取这些字段：

| 字段 | 来源位置 | 处理方式 |
| --- | --- | --- |
| 专业名称 | 第 1 页标题 | 自动抽取后人工校对 |
| 专业代码 | 第 1 页标题括号内 | 自动抽取后人工校对 |
| 江苏计划代码 | 计划简编中的 `X2 + 专业代码` 形式 | 自动/人工组合校对 |
| 层次 | 文件名或标题中的“专升本/专科” | 自动抽取 |
| 主考学校 | 专业目录表 | 单独从目录补齐；不要从专业计划 PDF 猜测 |
| 课程门数 | “学历层次与规格”段落 | 自动抽取后人工校对 |
| 总学分 | “学历层次与规格”或课程表合计 | 双源校对 |
| 课程表 | “考试课程与学分”表 | XML 坐标抽取后人工校对 |
| 实践要求 | “实践性环节学习考核要求”段落 | 摘录关键规则 |
| 学位 | “学历层次与规格”段落 | 摘录，不扩写 |

## 5. 课程表规范化

专业页统一使用以下表头：

```markdown
| 序号 | 课程代码 | 课程名称 | 学分 | 考试方式 | 课程页 | 建设优先级 |
| ---: | --- | --- | ---: | --- | --- | --- |
```

规范：

1. 同一序号下的理论课和实践课分成两行，例如：
   - `13013 高级语言程序设计`
   - `13014 高级语言程序设计（实践）`
2. 毕业论文、毕业设计、综合考核等如官方表格列出，保留在表中，但标记为“不计学分”。
3. `课程门数`按官方毕业要求写，不要简单按 Markdown 表格行数计算。实践环节、毕业设计是否计入，以官方原文为准。
4. 公共课程页已存在时链接到 `../../courses/<课程代码>.md`；不存在时写“待建”。
5. `建设优先级`建议：
   - `P0`：跨专业复用率高或学习门槛高的公共课。
   - `P1`：专业核心笔试课。
   - `P2`：实践课、毕业论文/设计、低复用度内容。

## 6. 生成专业 Markdown

复制 `templates/major.md`，填充字段后保存到：

```text
docs/jiangsu/majors/<专业代码>-<english-slug>/index.md
```

命名示例：

```text
docs/jiangsu/majors/080901-computer-science-and-technology/index.md
```

页面必须包含：

1. 基本信息表。
2. 一句话定位。
3. 政策状态。
4. 毕业要求。
5. 2024 版课程清单。
6. 实践与毕业环节。
7. 课程资料建设路线。
8. 新旧计划与顶替说明。
9. 官方来源。
10. 待补全 / 待校对。

## 7. 教材 ISBN 收集注意事项

教材 ISBN 用于帮助后续定位正版纸书、出版社页面、图书馆馆藏或合法电子书入口；ISBN 本身不代表可以托管或分发教材电子版。

项目内不保存教材电子书 PDF。已收集但不适合发布的教材 PDF 放在项目外本地归档 `C:\WorkSpace\project\FinalGo_local_archive\e-books\jiangsu\`，公开文档只记录教材计划、ISBN、出版社等可追溯信息。

批量收集教材时按以下顺序处理：

1. 先从江苏省教育考试院当次“开考课程教材计划表”抽取课程代码、课程名称、教材名称、作者、出版社、版次。
2. 再用 `教材名称 + 作者 + 出版社 + 版次` 补 ISBN；不要只靠课程名称搜索。
3. 同一课程如果有多个教材行，例如“教材 + 自学指导”或“大纲 + 教材”，要分别记录，不要合并成一个 ISBN。
4. 实践课、毕业论文、毕业设计通常没有独立 ISBN，应标记为“参考对应理论课教材 + 主考学校实践考核公告”。
5. 思想政治理论课必须按现行政策修正，不能只使用 2024 专业计划 PDF 中的旧代码。
6. ISBN 字段要保留来源和审核状态，例如 `isbn_source: 江苏教材计划/出版社页/省级教材表/人工校对`。
7. 搜索结果中出现的网盘、盗版 PDF、Z-Library 镜像、非授权上传站点，不得作为教材来源写入项目。

江苏专升本现行思想政治理论课是 3 门、共 9 学分：

| 课程代码 | 课程名称 | 学分 | 教材 ISBN |
| --- | --- | ---: | --- |
| 15040 | 习近平新时代中国特色社会主义思想概论 | 3 | `9787040610536` |
| 15043 | 中国近现代史纲要 | 3 | `9787040599015` |
| 15044 | 马克思主义基本原理 | 3 | `9787040599008` |

旧 `03708 中国近现代史纲要`、`03709 马克思主义基本原理概论` 只能作为历史计划或过渡顶替说明，不应作为现行专业页默认课程。

建议课程教材数据结构：

```yaml
course_code: "13003"
course_name: "数据结构与算法"
province: "江苏"
exam_period: "2025-10/2026-01"
textbook_name: "数据结构与算法"
author: "辛运帏、陈朔鹰"
publisher: "机械工业出版社"
edition: "2024 年版"
isbn: "9787111761037"
isbn_source: "江苏教材计划 + 人工检索校对"
source_file: "docs/jiangsu/source/textbooks/jiangsu-2025-10-2026-01-schedule-textbooks.xml"
status: "checked"
notes: "不托管教材电子版"
```

## 8. 人工审核关卡

每个专业页发布前至少做一次人工审核：

- [ ] 专业代码、专业名称、层次与官方目录一致。
- [ ] 主考学校来自官方目录，不从 PDF 文件名推断。
- [ ] 课程代码、课程名称、学分、考试方式与 XML/PDF 一致。
- [ ] 总学分与课程表合计、官方段落一致。
- [ ] 实践课、毕业设计没有被误算进课程门数。
- [ ] 当次教材和考纲没有从旧公告复制。
- [ ] 页面中所有“待补全/待校对”都说明原因。

## 9. 适合后续自动化的部分

后续可以写脚本批量完成：

1. 遍历专业计划 PDF。
2. 调用 `pdftohtml -xml` 和 `pdftotext -layout` 生成 raw 产物。
3. 从文件名解析序号、专业名称、层次。
4. 从 raw XML 第一页解析专业代码。
5. 生成 `plan.normalized.html`，把课程表整理为真实 HTML 表格。
6. 从规范化 HTML 生成 `plan.extracted.md`。
7. 按 `templates/major.md` 生成或更新 `index.md`。
8. 在页面顶部标记 `数据状态：机器初稿，待人工审核`。

当前项目可用批处理脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\process-pdfs.ps1 -Force
```

批处理结果记录在：

- `source/pdf-processing-report.md`
- `source/pdf-processing-manifest.csv`

不建议完全自动化的部分：

- 主考学校字段：必须从官方目录校对。
- 新旧课程顶替：表格复杂，容易被 OCR/坐标抽取误拼。
- 教材与考纲：以当次考试公告为准，不能从专业计划中推断。
- 真题：官方公开原件可入库；第三方真题和答案解析需要来源分级，只能做线索或项目外本地参考。

## 10. 本次样板

已按该流程产出的样板页：

- [计算机科学与技术（专升本）](./majors/080901-computer-science-and-technology/)
- Raw XML 来源：`majors/080901-computer-science-and-technology/sources/plan.raw.xml`

已批处理完成：

- 54 个专业考试计划 PDF。
- 16 个共享 PDF，其中包含政策/目录、教材计划和官方独立考纲 PDF。
