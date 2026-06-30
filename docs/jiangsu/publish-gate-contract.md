# 课程页 🟢 可发布闸门契约(轨道 A 交付包)

> 关联:CHO-106(轨道 A 内容填埋)。本文件锁定「🟡 机器初稿 → 🟢 可发布」的机器闸门与人工前置条件,供 PR 审查团队、法务合规、QA 提测三方对齐。
> 状态语义以仓库现行约定 + 本 issue 为准:🔴 建设中 / 🟡 机器初稿(带 ⚠️ 横幅,不可对外) / 🟢 可发布。

## 一、机器闸门(由 `scripts/build-course-pages.py` 强制执行)

页面在 frontmatter `状态` 字段以 `🟢` 开头即触发发布闸门。闸门会在以下任一不满足时**阻断构建**(`result.errors`):

| 闸门码 | 条件 | 当前 15044 状态 |
| --- | --- | --- |
| `HUMAN_REVIEW_REQUIRED` | frontmatter 须有 `reviewed: true` 且 `reviewer: <姓名>` 非空 | ❌ `reviewed: false`、`reviewer: null` |
| `PUBLISH_PENDING_REQUIRED_DATA` | 元信息 `数据状态`/`发布日期` 不得含 `待校对`/`待统计`/`待收集`/`待核验`/`待确认`;frontmatter `exam_source_status`/`exam_analysis_status` 同理;`replacement_confirmed` 须为 true/yes/confirmed | ❌ 全页遍布 `待校对`/`待统计`/`待收集`,真题三考期待核验 |
| `REPLACEMENT_FREE_TEXT_BYPASS` | 「新旧课程顶替」区块不得同时存在 4 字段表与自由文本 blockquote(含「替代」字样) | ✅ 本 PR 已消除 15044 原自由文本 bypass,增量信息已并入 4 字段表/区块说明;当前无该项阻塞 |
| `EXAM_INDEX_SCOPE_MIXED` / `EXAM_INDEX_DUPLICATED_SCOPE` | 考期索引现行/历史不得混排、不得重复;须用 frontmatter `current_exam_periods` / `legacy_comparison_periods` 结构化列表分离 | ⚠️ 当前 2024-10 行混排 15044/03709 → 🟢 前须拆为结构化列表;真题来源与原件采集由 zikao-materials 链路负责,PR 审查团队仅按已入库材料背书内容口径 |
| `CONTENT_REVISION_MISMATCH` | frontmatter `content_revision`(若有)须匹配构建 HEAD commit | ✅ 当前未设该字段 |

> 闸门只在页面**声称 🟢** 时阻断;🟡/🔴 仅产出 advisory warning,不阻断。当前 15044 处于 🟡,构建通过(75 页,1 条与本题无关的 `majors/index.md` 秘书学目录 warning)。

## 二、人工前置(机器无法自证,🟢 前必须由对应角色完成)

按 issue 验收三态 + 仓库 `templates/course-review-checklist.md`(20 项模板,本批课程按其中 17 项高风险/适用项逐项签名):

1. **高风险区块内容审查背书**(PR 审查团队):政策与时效、考纲概览(范围/分值比例)、教材信息(版本/ISBN)、章节知识树(覆盖率 ≥ 90%)、高频概念表(考频须有真题依据)、真题解析(不含第三方原题全文)、来源与引用(链接可访问)、新旧顶替关系(标准 4 字段)。
   - 15044 知识树覆盖率已机器达 100%(78/78),可作机器侧证据;考频字段(`待统计`)须等 zikao-materials 真题原件入库后据实填写,**不得机器编造**;真题未入库时维持空态,不阻塞内容门。
2. **法务合规审视**(法务合规团队):涉版权(真题/教材 ISBN)、考生 PII、AI 生成声明的区块,交付前置 🟢 前须显式带上法务合规团队。真题解析红线:不得含第三方原题全文(CHK-09),解题思路须描述通用方法论不绑定具体题号/参数(CHK-10)。
3. **背书可追溯**(CHK-12):`reviewed: true` + `reviewer` 须由 PR 审查团队在对应 Git commit / PR review 中留下可追溯背书,**不得由自动化 agent 伪造**。

## 三、机器侧已就绪 / 待人工的 15044 现状

- ✅ 13 必填区块齐全;知识树 78/78 知识点(100%);3 类题型四要素模板;3 道典型题解析含版权声明;新旧顶替 4 字段表;面包屑/相关课程链接。
- ✅ 教材信息机器可核验部分已与官方教材计划一致:15044 / 马克思主义基本原理 / 本书编写组 / 高等教育出版社 / 2023 年版(源自 `source/processed/textbooks/.../document.extracted.md`)。
- ⚠️ ISBN 字段为「待补充」:官方教材计划源数据**不含 ISBN**,需从教材实物或出版社官网核验(CHK-03 的人工部分)。
- ⚠️ 真题 2025-04 / 2025-10 缺失:`source/past-papers/` 仅有 README,无任何 A 级官方真题原件;来源与原件采集由 zikao-materials 链路负责,入库前考频/真题分布表为空态保留(符合 issue 空态规则:不删区块、不虚构,不阻塞内容门)。
- ⚠️ 适用专业清单仅覆盖 1 个专业(源数据限制):15044 实为全省公共必修,待全量专业计划简编补齐后脚本更新。

## 四、交付路径

1. 后端整合 Agent:锁契约(本文件)+ 预置机器侧 frontmatter 待背书字段(不伪造签名)→ 推分支 + draft PR 回链本 issue。
2. PR 审查团队:按 17 项高风险/适用项完成内容审查背书;在 PR review / 对应 commit 中留下可追溯结论,并按真实结论回填 `reviewed: true` + `reviewer`。
3. zikao-materials 链路:负责真题来源/原件补采;真题未入库时相关区块保持空态,不作为内容门阻塞。
4. 法务合规团队:版权/PII/AI 声明审视通过。
5. QA:提测,跑 `build-course-pages.py` + `check-source-links.py` 全绿后置 🟢。
6. 按 [[squad-handoff]] assign 推动流转。

## 五、待确认(不阻塞机器侧推进,影响 🟢 语义)

issue 末尾的冲突:父 issue 把「可发布」等同 🟡,本 issue 取 🟢=可发布。本交付包以本 issue 为准(🟡=机器初稿不可对外)。若负责人坚持 🟡=可发布,则须移除 15044 顶部「未经校对」横幅与审核清单门槛——二者不能并存。
