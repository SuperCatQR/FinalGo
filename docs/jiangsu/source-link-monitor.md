# 考纲/来源链接变更主动检测 Runbook (CHO-14)

定期检查课程页「来源与引用」/「考纲与教材」/「真题索引」节中所有外部 URL 的
可访问性，并对**权威考纲页**（`jseea.cn`）做内容哈希漂移检测。检测到需降级的
变更时，按 PRD §4.2 双向状态回退规则映射出降级建议，交维护者执行。

> 本机制只做「检测 + 告警」，**不修改课程 Markdown，不做任何部署**。
> 降级（🟢→🟡 / 🟡→🔴）是内容侧人工动作。

## 组成

| 文件 | 作用 |
| --- | --- |
| `scripts/check-source-links.py` | 检测脚本（仅依赖 Python 标准库，无需 venv） |
| `docs/jiangsu/source-links.baseline.json` | 链接基线：每个 URL 的上次状态与权威页内容哈希 |
| `.github/workflows/source-link-monitor.yml` | CI：每周一 03:17 UTC 跑一次 + 可手动触发 |
| `site/source-link-report.md` / `.json` | 每次运行产出的报告（`site/` 已 gitignore，CI 里走 artifact） |

## 设计要点（避免误报）

- **网络故障 ≠ 链接失效**：超时 / DNS / TLS 失败被判为 `inconclusive`，**不触发降级**。
  这样从境外 CI runner 访问 CN 站点被限流时不会误判为 🔴。
- **只对权威考纲页比哈希**：`jseea.cn` 的考纲页比内容哈希（已剥离时间戳/长数字串降噪）；
  `zikaosw` / `zikao365` / `bilibili` 等第三方真题/参考站只查存活，不比哈希（避免广告/动态标记噪声）。
- **批量腐烂识别**：同一主机 ≥3 个且 ≥60% 链接同时失效时，报为**一条主机级告警**，
  提示「疑似省级网站改版，请人工重新定位入口」，而非逐页 🔴。

## 本地运行（命令级可复现）

```bash
# 1. 只抽取链接、不联网（冒烟测试，确认章节解析正确）
python scripts/check-source-links.py --offline

# 2. 联网检测，对比现有基线，产出报告（不改基线）
python scripts/check-source-links.py --timeout 20 --retries 2

# 3. 查看报告
cat site/source-link-report.md
python -c "import json;print(json.load(open('site/source-link-report.json'))['actionable_count'])"

# 4. 初始化 / 重建基线（首次或人工确认变更后）
python scripts/check-source-links.py --init-baseline   # 首次建基线
python scripts/check-source-links.py --update-baseline # 对比后把当前结果写回基线

# 5. 严格门禁（有需降级变更则退出码=2，供 pre-commit/CI 卡口用，可选）
python scripts/check-source-links.py --fail-on-change
```

退出码：`0`=正常（含 inconclusive）；`2`=`--fail-on-change` 且检出需降级变更；`1`=脚本内部错误。

## CI 行为

`source-link-monitor.yml`：

1. 每周一 03:17 UTC 自动跑（也可在 Actions 页 `Run workflow` 手动触发）。
2. 跑 `check-source-links.py`，报告写入 job summary + 上传 artifact（保留 30 天）。
3. **检出需降级变更或批量腐烂时**，自动开（或追加评论到）一个标题含 `[link-monitor]`
   的 GitHub issue，打 `source-link-rot` 标签。该 issue 仅作技术告警，
   **派活与降级执行仍在 Multica issue 进行**。
4. 手动触发并勾选 `update_baseline=true` 时，把刷新后的基线提交到
   `chore/refresh-source-link-baseline-*` 分支并开 PR，等人工确认后合并。

CI 失败排查：先本地按上面「本地运行」第 2 步复现，不在 yaml 上盲改。
查 CI：`gh run list --workflow source-link-monitor.yml`、`gh run view <id> --log-failed`。

## 检出变更后的处理路径

| 报告中的变更 | 含义 | 建议降级（PRD §4.2） | 谁来做 |
| --- | --- | --- | --- |
| `went_dead` | 考纲链接失效（确定性 4xx/5xx） | 🟡→🔴：内容无可信来源支撑，降至骨架级 | 内容侧维护者 |
| `content_changed` | 权威考纲页内容变更 | 🟢→🟡：已校对内容需重新核对 | 内容侧维护者 |
| 批量腐烂主机 | 整站疑似改版 | 先人工重新定位新入口，再决定是否逐页降级 | 内容侧 + 维护者 |
| `new` / `recovered` | 新增链接 / 已恢复 | 无需处理（已自动纳入基线对比） | — |

确认并处理完变更、新入口已写回课程页后，用 `--update-baseline`（或 CI 手动
dispatch 勾选 `update_baseline`）刷新基线，关闭告警 issue。

## 红线

- 不把任何凭证写进脚本 / yaml；CI 仅用内置 `GITHUB_TOKEN`（最小权限 `issues: write`）。
- 不在检测里自动改课程页状态——降级是人工动作，脚本只给建议。
- 网络不确定一律不触发降级，避免限流误报。
