# 江苏自考一站式解决（jiangsu-zikao-aio）

江苏省自学考试资料库。Markdown 源 → Python 生成静态站点 → GitHub Pages 发布。

- 站点：<https://supercatqr.github.io/jiangsu-zikao-aio/>
- 数据源优先级：江苏省教育考试院官方公告与附件 > 主考学校转发公告 > 后续人工校对资料。

## 目录

```text
jiangsu-zikao-aio/
├── content/jiangsu/       # 发布内容：majors, courses, index.md
├── sources/jiangsu/       # 原始 PDF、机器抽取产物、清单、报告
├── ops/                   # 元文档：政策、工作流、闸门、模板、外链基线、蓝图
├── scripts/               # 构建/巡检/PDF 处理脚本 + CSS 模板
├── archive/               # 历史存档（不参与发布）
├── build.toml             # 路径 + 外链巡检配置
├── .github/workflows/     # Pages 部署 + 外链监控
└── README.md GIT_GUIDE.md reasonix.toml
```

三分区语义：

- **content/** 会被构建器渲染进 `site/`；改路径先看 `build.toml`。
- **sources/** 原始与机器产物；`sources/<省>/` 独立分省。
- **ops/** 元文档，供内容作者查阅；不进入 `site/`。

新增省份：`content/<省>/`、`sources/<省>/`、`ops/<省>/` 三条支线一起加。

## 常用命令

构建静态站点（Pages CI 也跑这条）：

```bash
python scripts/build-course-pages.py --base /jiangsu-zikao-aio/
```

本地预览：

```bash
python scripts/build-course-pages.py --base /
open site/index.html
```

外链巡检（离线快速统计文件覆盖）：

```bash
python scripts/check-source-links.py --offline
```

PDF 批处理（Windows PowerShell）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\process-pdfs.ps1 -Force
```

## 目录职责与放置规则

见 [ops/project-folders-structure-blueprint.md](ops/project-folders-structure-blueprint.md)。

## 贡献

Git 规范：[GIT_GUIDE.md](GIT_GUIDE.md)。课程页发布前必过 [ops/jiangsu/course-review-checklist.md](ops/jiangsu/course-review-checklist.md)。
