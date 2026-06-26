# Git 使用规则（江苏自考一站式解决）

本项目以 Git 管理代码与内容源数据。规则从简,够用为度。

## 仓库

- 远程:`https://github.com/SuperCatQR/FinalGo.git`
- 主分支:`main`(受保护,不直接 push 大改动,走分支 + PR)

## 分支

- `main`:可发布/可构建的稳定状态。
- 功能/内容分支:`feat/<课程或专业代码>`、`fix/<简述>`、`chore/<简述>`。
  例:`feat/13000-english-content`、`fix/15040-canonical-path`。
- 分支基于最新 `main` 切出,完成后通过 PR 合回。

## 提交信息

采用简化版 Conventional Commits:

```
<type>: <简短描述>

<可选正文:为什么这么改>
```

`type` 取值:`feat`(新增内容/功能)、`fix`(修正)、`docs`(文档)、
`chore`(脚手架/依赖/构建)、`refactor`(重构,不改行为)。

例:`feat: 15043 中国近现代史纲要迁移到 v2 模板`。

## 禁止提交

由 `.gitignore` 兜底,务必不要强行 `git add -f` 以下内容:

- 平台/工具运行时目录:`.multica/`、`.agent_context/`、`.claude/`、`.opencode/`、`.reasonix/`
- 构建产物:`site/`(可由 `python scripts/build-course-pages.py` 重新生成)
- 缓存与依赖:`__pycache__/`、`node_modules/`
- 任何密钥、token、`.env`、证书文件

## 版权红线(内容侧)

- 真题只放官方/第三方**入口链接**,不转载原题全文。
- 引用考纲/教材须在「来源与引用」节标注来源与时效。

## 常用命令

```bash
git switch -c feat/xxx        # 从 main 切新分支
git add <files>               # 按需暂存,避免 git add .
git commit -m "feat: ..."     # 提交
git push -u origin feat/xxx   # 首次推送并建立跟踪
# 在 GitHub 上开 PR 合回 main
```
