# 江苏自考真题原件入库规则

本目录只保存 A 级来源的官方公开真题原件，按课程代码和考期组织。

推荐路径：

```text
docs/jiangsu/source/past-papers/<course-code>/<year>-<period>-<source-slug>.pdf
```

示例：

```text
docs/jiangsu/source/past-papers/02333/2025-04-official.pdf
```

处理规则：

1. 每个文件必须能追溯到江苏省教育考试院、中国教育考试网或主考学校公开页面。
2. 文件名必须包含年份和考期，例如 `2025-04`、`2025-10`。
3. 下载后运行 `scripts/process-pdfs.ps1 -Force`，处理产物会进入 `docs/jiangsu/source/processed/past-papers/<course-code>/`。
4. 自考365、自考生网/攀知自考、B站、网盘、商品页等第三方资料不放入本目录；如需用于人工参考，放到项目外 `C:\WorkSpace\project\FinalGo_local_archive\past-papers\jiangsu\`。
