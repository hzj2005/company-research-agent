# 简历项目描述与面试追问（S9）

> **一句话**：一个基于 LangGraph 的公司调研 Agent 流水线（Apache-2.0 开源项目二次开发），主图 + 并行检索子图 + 证据判定/回退 + 人工复核，配 fixture / live 双轨评测与额度护栏。**下面每个数字都能用一条命令复现**，复现不了的不写。

**项目定位**：输入公司名，输出带引用的 Company / Industry / Financial / News 四栏简报；重点不在「接了个模型」，而在**证据不足时敢拒答、真实调用前先算额度、分不清「引用对得上」和「事实对」时如实标未测**。

**归因**：基于 `guy-hartstein/company-research-agent`（Apache-2.0，上游 commit `23fe92d`）二次开发，`LICENSE` 与上游 commit 均保留；不写「独立开发」「从零自研」。

## 1. 可直接粘贴的简历条目

> 粘贴版不带编号；编号与出处见 §2，面试前按 §3 过一遍。按 Agent 工程 / RAG / 后端三个方向重排的版本见 `docs/RESUME_VARIANTS.md`。

- **图编排与可恢复的人工复核（LangGraph）**：在上游线性 LangGraph 流水线（一路 `add_edge` 串到底、无分支、无 checkpoint）的基础上重构：主图状态机串联「检索 → 结构化抽取 → 证据判定 → 成稿」，检索侧改为 `Send` 动态派发的并行子图，按栏目白名单只重跑证据不足的分支（输出 Company / Industry / Financial / News 4 个栏目）；全流程落 SQLite checkpoint，成稿前可 `interrupt()` 暂停、换进程 `Command(resume=...)` 续跑。
- **人工核验标准答案与可回归的评测台**：为真实报告建人工核验标准答案（25 条事实 / 5 家公司），二次复核修订 11 条、替换 6 条打不开的原始出处；把引用判定从词法代理升级为 AI 语义批改（1 次请求 / 2776 tokens），产物显式标注非人工裁定、不作为对外指标。评测台内置 8 项指标 / 6 个评测组，A/B 关掉行内引用即让引用分归零、幻觉代理升满，而事实准确率不变——证明 fixture 满分只是流程契约分。
- **真实检索链路与额度纪律**：接真实 Tavily + 阿里云 qwen-plus 跑通端到端：三重 opt-in 默认全关、用户额度硬上限 50 credits、进程内调用预算按次扣减、sha256 检索缓存（单次命中 1 次且不扣额度）、dry-run 先预演 12 条 query；一次真实调研发起 3 次联网检索 / 6 credits，完成 4 次模型请求 / 7896 tokens，产出 4998 字符、11 条来源、27 处行内引用的简报。
- **从真机报告定位并修复合成语料测不出的问题**：真机报告暴露了三类合成语料测不出的问题：同一栏目成立年份自相矛盾、总部写成伦敦门牌、Financial 栏目整栏是马来西亚上市公司 Notion VTec Berhad 的股价指标；回看原文确认前两处同源——CB Insights 收录的其实是另一家同名公司（`notion.online`）。按「标题交易所代码绑定 + 跨文档官网域名一致性」加实体消歧，真实语料触发 4 次拒绝、逐篇回放核对全为异实体、无一误杀；同栏目多值冲突改为显式标注，不替读者取舍。重跑 4 家公司 / 20 条人工核验标准答案：8 条被完整支持、2 条判为反证、10 条未写到，引文逐字校验失败 0 条。

## 2. 展开版：每条的技术细节与证据

### 2.1 图编排与可恢复的人工复核（LangGraph）

**简历写法**：在上游线性 LangGraph 流水线（一路 `add_edge` 串到底、无分支、无 checkpoint）的基础上重构：主图状态机串联「检索 → 结构化抽取 → 证据判定 → 成稿」，检索侧改为 `Send` 动态派发的并行子图，按栏目白名单只重跑证据不足的分支（输出 Company / Industry / Financial / News 4 个栏目）；全流程落 SQLite checkpoint，成稿前可 `interrupt()` 暂停、换进程 `Command(resume=...)` 续跑。

**展开（面试自述用）**：

- 条件边三路（pass / retry / degrade）由 `evidence_check` 写状态、`route_after_evidence` 以纯函数读状态；循环终止条件是 `retry_count ≥ max_retry`，不让模型自述「够了」。
- 栏目级重试用 `all()` 而不是 `any()`：一个栏目耗尽额度不会把还有额度的栏目一起降级；`retry_count` 按栏目独立计数，避免刚开始回退的栏目错拿别栏轮次。
- 子图用 `input_schema / output_schema` 隔离，`Send` 只带编排参数与 `active_section`，不把累积字段塞进并行分支（否则主图 reducer 会重复累加）。
- `interrupt()` 恢复时节点会从头重跑，所以复核节点不做副作用；非法决策按「不批准」处理（fail-safe），栏目名走白名单过滤，防止任意字符串污染 state。

**证据**：`F26`（见 `docs/RESUME_EVIDENCE.md` §2）；代码位置：`graph/builder.py`、`graph/conditions.py`、`graph/subgraphs/research.py`、`graph/nodes/human_review.py`、`persistence/checkpointer.py`。

### 2.2 人工核验标准答案与可回归的评测台

**简历写法**：为真实报告建人工核验标准答案（25 条事实 / 5 家公司），二次复核修订 11 条、替换 6 条打不开的原始出处；把引用判定从词法代理升级为 AI 语义批改（1 次请求 / 2776 tokens），产物显式标注非人工裁定、不作为对外指标。评测台内置 8 项指标 / 6 个评测组，A/B 关掉行内引用即让引用分归零、幻觉代理升满，而事实准确率不变——证明 fixture 满分只是流程契约分。

**展开（面试自述用）**：

- 三层边界写死在 golden 里：事实层（用户逐条复核）、引用层（换过 URL 的条目本项目未重抓，明确标 `citation_layer_usable_as_metric=false`）、覆盖层（只有一家公司有真实报告可比）。
- judge 只送 `claim_id` + 期望文本 + 报告正文，不送出处；证据句必须能在 `## References` 之前的正文里逐字（归一化后）找到，找不到标 `quote_check_failed`；`max_retries=0` 锁死一次请求，失败如实落盘不重试。
- 修完 judge 的一批问题后不重跑模型，改用事后审计按新口径重算：差异 0 条，原始产物用 sha256 锚定。
- A/B 是常设防线：关掉行内引用后 `citation_traceability` 从满分掉到零、`hallucination_rate` 升满，而 `fact_accuracy` 纹丝不动——那个满分只测流程，不测效果。

**证据**：`F13`、`F14`、`F15`、`F16`、`F19`、`F20`、`F21`、`F22`、`F27`（见 `docs/RESUME_EVIDENCE.md` §2）；代码位置：`evals/judge.py`、`evals/metrics.py`、`evals/build_golden_live.py`、`evals/build_live_report.py`、`.github/workflows/eval.yml`。

### 2.3 真实检索链路与额度纪律

**简历写法**：接真实 Tavily + 阿里云 qwen-plus 跑通端到端：三重 opt-in 默认全关、用户额度硬上限 50 credits、进程内调用预算按次扣减、sha256 检索缓存（单次命中 1 次且不扣额度）、dry-run 先预演 12 条 query；一次真实调研发起 3 次联网检索 / 6 credits，完成 4 次模型请求 / 7896 tokens，产出 4998 字符、11 条来源、27 处行内引用的简报。

**展开（面试自述用）**：

- 三重开关是「与」关系：`APP_MODE=live` + `TAVILY_LIVE_ENABLED=true` + `TAVILY_MAX_CALLS>0`，任一不满足直接抛 `LiveRetrievalDisabled`；装了 key 也调不动。
- `CallBudget.consume()` 在真正发请求前扣额度，用尽抛 `TavilyBudgetExceeded`，不重试、不绕过；dry-run 用一个一调用就抛错的 `DryRunSentinel` 兜底，护栏被误改也到不了网络。
- 缓存 key 是 `(query, section, max_results, search_depth, topic)` 的 sha256，命中直接返回 Document、不扣额度，所以一次真实调用之后可以离线反复复现。
- 测试注入 fake client 与替身 retriever，永不实例化 `AsyncTavilyClient`；回归环节另装 socket 禁网守卫，实测拦截外部连接为零。

**证据**：`F02`、`F03`、`F04`、`F05`、`F06`、`F07`、`F08`、`F09`、`F10`、`F12`（见 `docs/RESUME_EVIDENCE.md` §2）；代码位置：`capabilities/tavily_retriever.py`、`capabilities/structured.py`、`evals/live_dryrun.py`、`evals/live_run.py`。

### 2.4 从真机报告定位并修复合成语料测不出的问题

**简历写法**：真机报告暴露了三类合成语料测不出的问题：同一栏目成立年份自相矛盾、总部写成伦敦门牌、Financial 栏目整栏是马来西亚上市公司 Notion VTec Berhad 的股价指标；回看原文确认前两处同源——CB Insights 收录的其实是另一家同名公司（`notion.online`）。按「标题交易所代码绑定 + 跨文档官网域名一致性」加实体消歧，真实语料触发 4 次拒绝、逐篇回放核对全为异实体、无一误杀；同栏目多值冲突改为显式标注，不替读者取舍。重跑 4 家公司 / 20 条人工核验标准答案：8 条被完整支持、2 条判为反证、10 条未写到，引文逐字校验失败 0 条。

**展开（面试自述用）**：

- 不按置信度选一条的理由很具体：真机里那篇错的 score 反而更高，按分数保留会留下错的。来源本身就错时，「让读者看见冲突」比「替他选」更诚实。
- 隔离器有两道护栏：整栏全被拒时全部放行并留痕（规则在这家公司名上失效，不许清空栏目）；开关关闭时单文档规则与跨文档一致性必须同时停（第一版只停了前者，离线回放对照时抓到）。
- 修复后瓶颈换了：10 条未写到，说明问题从「说错」变成「没说」，那是检索召回与栏目分配，不是消歧能解决的。真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价仍一律标未测。

**证据**：`F32`、`F33`、`F34`、`F35`、`F36`、`F37`、`F39`（见 `docs/RESUME_EVIDENCE.md` §2）；代码位置：`capabilities/entity_guard.py`、`capabilities/conflict.py`、`docs/LIVE_SCORE.md`、`docs/LIVE_BATCH.md`、`evals/live_quality.json`。

## 3. 面试追问清单

> 按「设计取舍 / 数字口径 / 问题定位 / 复现与额度」分组；每个回答都指到具体文件，答完可以当场打开给对方看。

### 设计取舍

**Q1　为什么用 LangGraph，而不是一个 while 循环 + 工具调用？**

三个硬需求：① 需要「证据不足 → 改写 query → 只重跑不足栏目」的可控回环，终止条件必须是规则而不是模型自述；② 需要 checkpoint 与中断恢复，人工复核要能跨进程续跑；③ 需要按栏目并行（`Send`），而不是串行跑几遍。手写循环也能实现，但状态、分支、恢复点都要自己维护，评审时很难证明没漏。

指路：`graph/builder.py`、`graph/conditions.py`、`graph/subgraphs/research.py`

**Q2　`Send` 子图比「在节点里循环几个栏目」好在哪？**

没被派发的 analyst 根本不执行，是图级并行而不是函数内循环；子图用 `input_schema / output_schema` 隔离，主图的累积字段不会被子图再写一遍（否则 reducer 重复累加）；`Send` 的 payload 只带编排参数 + `active_section`。踩过的坑：`Send` 必须从 `langgraph.types` 导入，`langgraph.constants` 在 1.2.22 起弃用。

指路：`graph/subgraphs/research.py`、`graph/subgraphs/state.py`

**Q3　「证据够不够」为什么不让模型自己判断？**

原版 prompt 写着 Never mention "no information found"，检索不到时模型会硬凑事实。这里把判定做成显式节点：按 `min_docs_per_section` 数去重后的 URL 数量，不够就是 insufficient；是否重试由 `retry_count` 与 `max_retry` 比较，不让模型说「够了」。好处是拒答可复现、可单测，坏处是阈值要靠配置调，所以我把它写进 settings 而不是代码。

指路：`graph/nodes/decide.py`、`graph/conditions.py`、`config/settings.yaml`

**Q4　条件边里 any 改 all，具体修了什么？**

原来 `any(count >= max_retry)`：只要有一个栏目用尽额度，其余还有额度的栏目也被一起降级，等于一个栏目拖垮整份报告。改成 `all(...)`：每个栏目用尽自己的额度才整体拒答；回退时只把「不足且仍有额度」的栏目写进白名单。这个 bug 是先写测试再改的，断言「一个有额度、一个没额度时仍应 retry」。

指路：`graph/conditions.py`、`tests/test_s4_subgraph.py`

**Q5　人工复核为什么放在成稿之前？**

因为 `briefing` 是依据 `degraded_sections` 决定哪些栏目拒答的，复核必须能改写这个字段，人工意见才会真正改变报告；放成稿之后只能改文字，改不了「出不出」。另外 `interrupt()` 恢复时节点从头重跑，所以节点里不做任何副作用，第一行就取 decision；非法输入按「不批准」处理，栏目名做白名单过滤。

指路：`graph/nodes/human_review.py`、`tests/test_s6_hitl.py`

**Q6　结构化抽取为什么不用 json.loads？**

解析交给 Pydantic：`with_structured_output(SectionBrief, method="function_calling")`，schema 里 `extra=forbid`，模型多塞字段当场报错触发重试，而不是被静默吞掉；重试耗尽整栏 degraded 并写 `review_notes`，绝不静默丢字段。每条 fact 的 `source_url` 必须落在本次传入的文档 URL 集合里，否则剔除并留痕——但这只是 URL 级回溯，不等于「来源内容确实支持结论」。

指路：`capabilities/structured.py`、`graph/contracts.py`

**Q7　checkpointer 为什么用 AsyncSqliteSaver？**

图里是 async 节点 + `ainvoke`，同步 `SqliteSaver` 的 `aget_tuple` 会抛 `NotImplementedError`，不能用；PostgresSaver 没实现，`config/loader.py` 里明确抛 `NotImplementedError`，我没有为了「看起来更生产」临时换持久化方案。

指路：`persistence/checkpointer.py`、`config/loader.py`

### 数字口径

**Q8　那几个 credits 是账单吗？**

不是。按 Tavily 官方 advanced = 2 credits/次 的规则乘以 `budget.calls_made` 推算，本项目从未查询或记录真实扣费。累计 8 = 最小探针 2 + 本次 6；50 是用户放行的硬上限，不是免费额度总量。

指路：`evals/live_run.json`、`docs/RESUME_EVIDENCE.md`

**Q9　fixture 里 fact_accuracy 是满分，能说明效果好？**

不能。fixture 是合成语料 + 零次外部调用，测的是「给定这批语料，流水线该产出什么」的契约，不是模型能力。反证就在 scorecard 里：关掉行内引用，`citation_traceability` 掉到零、`hallucination_rate` 升到满，而 `fact_accuracy` 一点没动——它只对「结论文本命中」敏感。

指路：`docs/LIVE_REPORT.md`、`evals/scorecard.json`

**Q10　`supported` 计数很低，是不是说明准确率很低？**

不是。可比对的是 5 条：其中判错的只有一部分，其余是「报告没写到」（not_mentioned），不是写反。样本只有一家公司一份报告，judge 还是 AI、未经人工抽检一致率校准，产物里明确写了 `usable_as_resume_metric=false`、`is_human_adjudicated=false`，所以我不把它写成指标。

指路：`evals/live_score.json`、`docs/LIVE_SCORE.md`

**Q11　为什么没有 p95 延迟和单份成本？**

只有一次真实运行，算不出 p95；62875.8 毫秒是单次墙钟，含网络往返，我在出处表里专门标了「不是 p95」。成本更直接：qwen-plus 不在 OpenAI 价目表内，`total_cost_usd` 是 null，我不拿别的模型单价套。

指路：`docs/RESUME_EVIDENCE.md`、`evals/live_run.json`

**Q12　为什么只有一家公司有真实报告？**

额度纪律。dry-run 预演显示一次完整调研最多会发 12 条 query，按官方计费最坏接近半个额度池；用户放行的上限是 50 credits，所以先跑一家把链路和产物验透。其余标准答案没有报告可比，就如实跳过 20 条，不拿标准答案给自己造卷子。

指路：`evals/live_dryrun.json`、`evals/live_score.json`

### 问题定位

**Q13　真机报告抓到的问题，为什么 fixture 测不出？**

fixture 语料同义自洽、每家公司只有一种实体、没有同名公司干扰，词法代理指标必然全绿。真机里出现的是：同栏目同时写两个不同成立年份；总部写成伦敦门牌、来源里混进 `medium.com`；Financial 栏目整栏是马来西亚上市公司 Notion VTec Berhad 的股票指标。这三类都不是「字面匹配」能抓的，得靠实体校验和跨句一致性。

指路：`docs/LIVE_SCORE.md`、`docs/LIVE_FINDINGS.md`

**Q14　judge 自己也有措辞错误，为什么没重跑？**

有一条 reason 说「未提 Ivan Zhao as CEO」，但报告 Industry 栏目其实出现过一次相关表述；判定（没有列出创始人）仍然成立，错的是措辞。重跑要再花一次请求，而且不改变结论，所以我保留结果、把瑕疵写进文档——这正好是「AI judge 不能当人工裁定」的实证。

指路：`docs/LIVE_SCORE.md`、`evals/live_score.json`

**Q15　引用层为什么标成不可用？**

二次复核时换掉了 6 条打不开的原始 URL，新页面本项目一次都没抓过（零调用），不能把旧页面的引文冒充新页面的内容；所以 golden 里直接写 `citation_layer_usable_as_metric=false`。事实层可用、引用层不可用，这两件事必须分开说。

指路：`docs/GOLDEN_LIVE.md`、`evals/golden_live.jsonl`

**Q16　如果继续做，优先级是什么？**

① 实体消歧：Financial 栏目先校验 ticker / 地区，同名公司直接过滤；② 冲突检测前置：同栏目同字段多值直接判 insufficient 回退，而不是出稿后才发现；③ 引用层补抓取，把 URL 级回溯升级为内容级；④ 扩样本到多家，到那时才谈得上准确率。

指路：`docs/LIVE_REPORT.md`、`docs/LIVE_FINDINGS.md`

### 复现与额度

**Q17　怎么证明简历上的数字不是编的？**

`uv run python -m evals.build_resume_evidence --verify` 会逐条起子进程执行文档里印出来的命令，把 stdout 与产物取值逐字比对；每条数字都带文件 + 字段 + 台账 commit；`tests/test_s9_resume.py` 再查一遍「简历里出现的每个数字都来自那张表」。

指路：`evals/build_resume_evidence.py`、`tests/test_s9_resume.py`

**Q18　怎么保证不烧额度？**

四道闸：三重 opt-in 默认全关、`CallBudget` 进程内硬预算、sha256 缓存命中不扣、dry-run 用一调用就抛错的 sentinel；测试和评测都装 socket 禁网守卫，回归全程零次外部检索。真实调用前先 dry-run 打印会发哪些 query，确认后才放行。

指路：`capabilities/tavily_retriever.py`、`evals/run_eval.py`

## 4. 不能写的话

- 不写准确率 / 幻觉率 / 引用可追溯率 / p95 延迟 / 成本单价：**未测**。
- 不把 fixture 的满分当效果：关一个开关分数就掉，它测的是流程契约。
- 不把 `supported` 计数当准确率：样本极少、AI 判定、未经人工校准。
- 不写「独立开发 / 从零自研」：本项目是 Apache-2.0 二次开发，必须保留归因。
- 不写「上线 / 甲方 / 用户量 / 提升 X%」：没有这些事实。

完整禁写清单（每条同样带出处与 commit）见 `docs/RESUME_EVIDENCE.md` §4。

## 5. 复现命令

```bash
uv run python -m evals.build_resume                 # 重新生成本文（0 调用）
uv run pytest -q tests/test_s9_resume.py           # 护栏：数字来源 / 禁写词 / 归因
uv run python -m evals.build_resume_evidence --verify   # 逐条执行出处表里的复现命令
uv run python -m evals.run_eval                    # fixture 评测分（0 外部调用）
```

## 6. 状态与边界

- 本文生成：零次外部连接、零次模型请求、零 Tavily credits。
- 所有数字来自 `docs/RESUME_EVIDENCE.md`；本文只做措辞组织，不新增任何测量。
- 真实效果指标仍为未测；这份材料只保证「写出来的每个数字查得到」，不保证「系统效果好」。
