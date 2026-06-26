# PDF 到 Markdown 四段式流水线

目标：把江苏自考官方 PDF 稳定转换成可审核、可发布、可追溯的 Markdown 页面。流水线不追求一步到位，而是把 PDF 解析拆成四个可检查阶段：

```text
PDF -> 原始 HTML/XML -> 规范化 HTML -> Markdown
```

## 为什么需要中间层

PDF 更接近“打印版面”，不是结构化文档。直接从 PDF 生成 Markdown 时，最容易在这些地方出错：

- 表格列错位，尤其是课程代码、课程名称、学分和考试方式。
- 同一序号下理论课与实践课被合并或拆错。
- 页眉、页脚、页码混进正文。
- 标题、说明段落和表格行的顺序被坐标抽取打乱。
- 后续修错时难以判断问题来自 PDF 抽取、结构识别还是 Markdown 模板。

因此本项目把“可追溯抽取”和“可发布内容”分开处理。

## 目录约定

每个专业的 PDF 转换产物放在本专业工作区：

```text
docs/jiangsu/majors/<major>/
├── index.md
├── sources.md
└── sources/
    ├── plan.raw.xml
    ├── plan.raw.txt
    ├── plan.normalized.html
    ├── plan.extracted.md
    └── plan.pipeline-notes.md
```

省级共享 PDF 按来源类型进入共享处理区：

```text
docs/jiangsu/source/
├── syllabus/
│   └── <course-code>-<slug>.pdf
├── past-papers/
│   └── <course-code>/<year>-<period>-<slug>.pdf
└── processed/
    ├── syllabus/<document>/
    ├── past-papers/<document>/
    ├── textbooks/<document>/
    └── documents/<document>/
```

文件职责：

| 文件 | 阶段 | 用途 |
| --- | --- | --- |
| `plan.raw.xml` | 原始 HTML/XML | `pdftohtml -xml` 产物，保留页码、坐标、字体、文本块 |
| `plan.raw.txt` | 原始文本 | `pdftotext` 或人工辅助文本，方便搜索和对照 |
| `plan.normalized.html` | 规范化 HTML | 将坐标文本整理成语义化章节、段落和表格 |
| `plan.extracted.md` | Markdown 草稿 | 从规范化 HTML 生成的专业页草稿或关键片段 |
| `plan.pipeline-notes.md` | 转换记录 | 记录命令、异常、人工修正和审核结果 |

## 阶段 1：PDF -> 原始 HTML/XML

输入：

```text
docs/jiangsu/source/2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）/<序号>.<专业名称>专业（层次）考试计划.pdf
```

输出：

```text
docs/jiangsu/majors/<major>/sources/plan.raw.xml
docs/jiangsu/majors/<major>/sources/plan.raw.txt
```

推荐命令：

```bash
pdftohtml -xml -i -noframes \
  "<source-pdf>" \
  "docs/jiangsu/majors/<major>/sources/plan.raw"

pdftotext -layout \
  "<source-pdf>" \
  "docs/jiangsu/majors/<major>/sources/plan.raw.txt"
```

保留原则：

- `raw` 层不做语义判断，不手工改内容。
- 页码、坐标、字体等抽取信息尽量保留，便于回溯。
- 这一层允许难读，但必须忠实。

验收点：

- 能定位标题、专业代码、课程表区域。
- XML 中课程代码、课程名称、学分文本没有明显缺失。
- 页眉、页脚、页码仍可识别，后续归一化时再移除。

## 阶段 2：原始 HTML/XML -> 规范化 HTML

输入：

```text
plan.raw.xml
plan.raw.txt
```

输出：

```text
plan.normalized.html
```

规范化 HTML 是本流水线最重要的中间层。它不追求样式还原，而是把 PDF 坐标文本转换成语义结构。

推荐结构：

```html
<article data-source-pdf="26.计算机科学与技术专业（专升本）考试计划.pdf">
  <header>
    <h1>计算机科学与技术（专升本）</h1>
    <dl>
      <dt>专业代码</dt>
      <dd>080901</dd>
      <dt>层次</dt>
      <dd>专升本</dd>
    </dl>
  </header>

  <section data-section="graduation-requirements">
    <h2>学历层次与规格</h2>
    <p data-source-page="1">...</p>
  </section>

  <section data-section="courses">
    <h2>考试课程与学分</h2>
    <table data-source-page="1">
      <thead>
        <tr>
          <th>序号</th>
          <th>课程代码</th>
          <th>课程名称</th>
          <th>学分</th>
          <th>考试方式</th>
        </tr>
      </thead>
      <tbody>
        <tr data-source-page="1">
          <td>1</td>
          <td>03708</td>
          <td>中国近现代史纲要</td>
          <td>2</td>
          <td>笔试</td>
        </tr>
      </tbody>
    </table>
  </section>
</article>
```

结构规则：

1. 使用 `article` 表示一个专业计划。
2. 使用 `section[data-section]` 表示稳定章节，例如 `courses`、`practice`、`degree`、`replacement`。
3. 表格必须使用真实 `table`，不要用空格对齐文本。
4. 每个来自 PDF 的段落或表格行尽量保留 `data-source-page`。
5. 推断字段用 `data-derived="true"` 标记，例如从文件名推断层次。
6. 人工修正用 `data-reviewed="manual"` 标记，并在 `plan.pipeline-notes.md` 说明。

验收点：

- 课程表列数稳定，课程代码、课程名称、学分、考试方式各在独立单元格。
- 理论课和实践课分别成行。
- 页眉、页脚、页码不进入正文。
- 章节顺序与官方 PDF 一致。
- 所有自动推断字段都能追溯来源。

## 阶段 3：规范化 HTML -> Markdown 草稿

输入：

```text
plan.normalized.html
templates/major.md
```

输出：

```text
plan.extracted.md
```

生成规则：

1. 从 `article > header` 填专业基本信息。
2. 从 `section[data-section="courses"] table` 生成课程清单。
3. 从实践、毕业环节、学历层次章节生成摘要段落。
4. 课程页链接只在课程页已存在时生成，否则写“待建”。
5. Markdown 草稿顶部必须写数据状态。

`plan.extracted.md` 是草稿，不直接等同于最终 `index.md`。最终专业页可以在草稿基础上人工润色，但不能删除来源和审核状态。

验收点：

- Markdown 表格列数正确。
- 学分数字、课程代码和课程名称与 `plan.normalized.html` 一致。
- 页面保留“待补全 / 待校对”。
- 官方来源指向原始 PDF、`plan.raw.xml`、`plan.normalized.html`。

## 阶段 4：Markdown 草稿 -> 发布页

输入：

```text
plan.extracted.md
sources.md
policies.md
```

输出：

```text
index.md
```

发布页允许做这些人工编辑：

- 增加一句话定位。
- 调整课程资料建设优先级。
- 补主考学校、教材来源、审核说明。
- 增加新旧计划顶替说明。

发布页不应做这些事：

- 不从未经校对的第三方资料补官方字段。
- 不托管教材电子书、第三方答案解析或来源不明的题库整理。
- 官方公开真题可以保存原件，但必须记录来源 URL、课程代码、年份、考期和审核状态。
- 不把旧思政课程当作现行默认课程，除非明确标注过渡或历史口径。
- 不删除来源链路。

## 转换记录模板

每次跑流水线时维护：

```markdown
# PDF 转换记录

| 字段 | 内容 |
| --- | --- |
| 源 PDF |  |
| 转换日期 |  |
| 转换工具 |  |
| 原始 XML | `plan.raw.xml` |
| 规范化 HTML | `plan.normalized.html` |
| Markdown 草稿 | `plan.extracted.md` |
| 数据状态 | 机器初稿 / 人工校对中 / 已校对 |

## 命令

```bash
pdftohtml ...
pdftotext ...
```

## 自动抽取问题

- [ ] 表格列是否错位：
- [ ] 页眉页脚是否混入：
- [ ] 课程代码是否缺失：

## 人工修正记录

| 位置 | 修改 | 原因 | 校对人/日期 |
| --- | --- | --- | --- |
```

## 自动化建议

脚本可以分三层写，避免一个脚本承担全部职责：

| 脚本 | 输入 | 输出 | 职责 |
| --- | --- | --- | --- |
| `pdf_to_raw` | PDF | `plan.raw.xml`、`plan.raw.txt` | 调用 Poppler，不做语义判断 |
| `raw_to_normalized_html` | `plan.raw.xml` | `plan.normalized.html` | 按坐标和文本规则识别章节、表格 |
| `normalized_html_to_markdown` | `plan.normalized.html` | `plan.extracted.md` | 套模板生成 Markdown 草稿 |

优先自动化：

1. 文件命名和目录创建。
2. PDF 到 raw XML/TXT。
3. 课程表初步识别。
4. Markdown 表格生成。

暂不完全自动化：

1. 主考学校字段。
2. 新旧计划顶替表。
3. 教材 ISBN 补全。
4. 实践考核和毕业设计的主考学校要求。

## 批处理脚本

当前项目提供全量批处理脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\process-pdfs.ps1 -Force
```

脚本会处理：

- `docs/jiangsu/source/2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）/*.pdf`
- `docs/jiangsu/source/*.pdf`
- `docs/jiangsu/source/textbooks/*.pdf`
- `docs/jiangsu/source/syllabus/*.pdf`
- `docs/jiangsu/source/past-papers/**/*.pdf`

输出：

- 专业计划 PDF：`docs/jiangsu/majors/<major>/sources/`
- 共享 PDF：`docs/jiangsu/source/processed/<category>/<document>/`
- 清单：`docs/jiangsu/source/pdf-processing-manifest.csv`
- 报告：`docs/jiangsu/source/pdf-processing-report.md`

## 当前样板

全部 PDF 已具备机器初稿产物。计算机科学与技术（专升本）示例：

```text
docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.raw.xml
docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.raw.txt
docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.normalized.html
docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.extracted.md
docs/jiangsu/majors/080901-computer-science-and-technology/sources/plan.pipeline-notes.md
```
