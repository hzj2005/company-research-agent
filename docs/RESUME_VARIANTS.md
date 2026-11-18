# 按岗位出多版简历措辞（S11）

> **一句话**：同一份事实、三种排法。三条正文一律复用 `docs/RESUME.md` 里那句出处表锚定过的原文，只换「先说什么」「说哪三条」和「为什么这对该岗位有用」——差异化不靠改事实句，靠换视角。

**归因不变**：基于 `guy-hartstein/company-research-agent`（Apache-2.0，上游 commit `23fe92d`）二次开发；三版都不写「独立开发」「从零自研」。

| 岗位 | 排序（从先到后） | 主要引用编号 |
|---|---|---|
| Agent 工程 | 「图编排与可恢复的人工复核」 → 「真实检索链路与额度纪律」 → 「从真机报告定位并修复合成语料测不出的问题」 | `F02`、`F03`、`F04`、`F05`、`F06`、`F07`、`F08`、`F09`、`F10`、`F12`、`F26`、`F32`、`F33`、`F34`、`F35`、`F36`、`F37`、`F39` |
| RAG / 检索增强生成 | 「从真机报告定位并修复合成语料测不出的问题」 → 「人工核验标准答案与可回归的评测台」 → 「真实检索链路与额度纪律」 | `F02`、`F03`、`F04`、`F05`、`F06`、`F07`、`F08`、`F09`、`F10`、`F12`、`F13`、`F14`、`F15`、`F16`、`F19`、`F20`、`F21`、`F22`、`F27`、`F32`、`F33`、`F34`、`F35`、`F36`、`F37`、`F39` |
| 后端 / 服务化 | 「真实检索链路与额度纪律」 → 「图编排与可恢复的人工复核」 → 「人工核验标准答案与可回归的评测台」 | `F02`、`F03`、`F04`、`F05`、`F06`、`F07`、`F08`、`F09`、`F10`、`F12`、`F13`、`F14`、`F15`、`F16`、`F19`、`F20`、`F21`、`F22`、`F26`、`F27` |

> 三版都不新增测量值。表里的编号指向 `docs/RESUME_EVIDENCE.md`，每个值都能用一条命令复现；复现不了的不写。

## 1. Agent 工程（LangGraph / 状态机 / 可恢复编排）

**一句话定位**：把上游那条一路 `add_edge` 串到底的线性流水线，改造成有分支、有回退、能中断恢复的 LangGraph 状态机；重点不是「用了 LangGraph」，而是「为什么这里必须用图」。

**为什么这么排**：这个岗位最先追问的是「为什么非要用图」，所以把 `Send` 并行、规则化终止条件、checkpoint 恢复三条排在最前；额度护栏放中间，说明外部调用不会失控；真机排障闭环收尾，证明这套编排在真实噪声下也修得动。

**可直接粘贴（三条，按此顺序）**：

- **图编排与可恢复的人工复核（LangGraph）**：在上游线性 LangGraph 流水线（一路 `add_edge` 串到底、无分支、无 checkpoint）的基础上重构：主图精简为「检索调度 → 成稿」三段式（grounding → research → briefing），检索侧拆成 Company / Industry / Financial / News 4 张**独立编译的子图**，由编排层用 `Send` 并行派发；每张子图自带 state schema 与自闭环（检索 → 消歧 → 抽取 → 证据判定 → 不足自返工（上限 `max_retry`）→ 写段落），主图不再协调回退；报告层退化为纯拼装工，统一编号与 References。全流程落 checkpoint，成稿前可 `interrupt()` 暂停、换进程 `Command(resume=...)` 续跑。
- **真实检索链路与额度纪律**：接真实 Tavily + 阿里云 qwen-plus 跑通端到端：三重 opt-in 默认全关、用户额度硬上限 200 credits、进程内调用预算按次扣减、sha256 检索缓存（单次命中 4 次且不扣额度）、dry-run 先预演 12 条 query；一次真实调研发起 0 次联网检索 / 0 credits，完成 4 次模型请求 / 12675 tokens，产出 4904 字符、18 条来源、32 处行内引用的简报。
- **从真机报告定位并修复合成语料测不出的问题**：真机报告暴露了三类合成语料测不出的问题：同一栏目成立年份自相矛盾、总部写成伦敦门牌、Financial 栏目整栏是马来西亚上市公司 Notion VTec Berhad 的股价指标；回看原文确认前两处同源——CB Insights 收录的其实是另一家同名公司（`notion.online`）。按「标题交易所代码绑定 + 跨文档官网域名一致性」加实体消歧，真实语料触发 4 次拒绝、逐篇回放核对全为异实体、无一误杀；同栏目多值冲突改为显式标注，不替读者取舍。重跑 4 家公司 / 20 条人工核验标准答案：8 条被完整支持、2 条判为反证、10 条未写到，引文逐字校验失败 0 条。

**每条对该岗位的价值（面试自述，不写进简历）**：

- 「图编排与可恢复的人工复核」——重点讲三件事：回环终止靠 `retry_count >= max_retry` 比较，不让模型自述「够了」；`Send` 是图级并行，没被派发的 analyst 根本不执行；子图用 `input_schema / output_schema` 隔离，避免主图 reducer 重复累加。三句都能当场指到代码。
- 「真实检索链路与额度纪律」——Agent 工程的一半是护栏：三重 opt-in 默认全关、`CallBudget` 在发请求前扣额度、sha256 缓存命中不扣、dry-run 用一调用就抛错的哨兵兜底——装上 key 也调不动。
- 「从真机报告定位并修复合成语料测不出的问题」——完整的排障闭环：报告里发现异常 → 回看缓存原文 → 定位到两处问题同源、是另一家同名公司 → 加交易所代码绑定与官网域名一致性两道规则 → 用真实语料回放确认无误杀。

**这一版不要写**：

- 别讲成「多智能体自主协同」或「自主规划」：这里没有 planner / reflection 式的自由编排，只有固定拓扑加规则分支，说大了会被当场追问到答不上来。
- 别写「支持任意工具调用」：工具只有检索与结构化抽取两个，没有通用 tool 注册表。

代码位置：`graph/builder.py`、`graph/conditions.py`、`graph/subgraphs/research.py`、`graph/nodes/human_review.py`、`persistence/checkpointer.py`、`capabilities/tavily_retriever.py`、`capabilities/structured.py`、`evals/live_dryrun.py`、`evals/live_run.py`、`capabilities/entity_guard.py`、`capabilities/conflict.py`、`docs/LIVE_SCORE.md`、`docs/LIVE_BATCH.md`、`evals/live_quality.json`。

## 2. RAG / 检索增强生成（检索、抽取、引用与评测）

**一句话定位**：检索增强的调研报告生成：真实网页检索 + Pydantic 结构化抽取 + 分层评测，把「说错」和「没说」分开计量，而不是揉成一个「准确率」。

**为什么这么排**：RAG 岗真正会追问两件事：「检索到错的东西怎么办」「引用到底能不能核」。所以实体消歧与冲突标注排第一，评测口径第二，检索侧工程第三——评测那一条恰好回答了「你怎么知道自己的引用是真的」。

**可直接粘贴（三条，按此顺序）**：

- **从真机报告定位并修复合成语料测不出的问题**：真机报告暴露了三类合成语料测不出的问题：同一栏目成立年份自相矛盾、总部写成伦敦门牌、Financial 栏目整栏是马来西亚上市公司 Notion VTec Berhad 的股价指标；回看原文确认前两处同源——CB Insights 收录的其实是另一家同名公司（`notion.online`）。按「标题交易所代码绑定 + 跨文档官网域名一致性」加实体消歧，真实语料触发 4 次拒绝、逐篇回放核对全为异实体、无一误杀；同栏目多值冲突改为显式标注，不替读者取舍。重跑 4 家公司 / 20 条人工核验标准答案：8 条被完整支持、2 条判为反证、10 条未写到，引文逐字校验失败 0 条。
- **人工核验标准答案与可回归的评测台**：为真实报告建人工核验标准答案（25 条事实 / 5 家公司），二次复核修订 11 条、替换 6 条打不开的原始出处；把引用判定从词法代理升级为 AI 语义批改（1 次请求 / 3435 tokens），产物显式标注非人工裁定、不作为对外指标。评测台内置 8 项指标 / 6 个评测组，A/B 关掉行内引用即让引用分归零、幻觉代理升满，而事实准确率不变——证明 fixture 满分只是流程契约分。
- **真实检索链路与额度纪律**：接真实 Tavily + 阿里云 qwen-plus 跑通端到端：三重 opt-in 默认全关、用户额度硬上限 200 credits、进程内调用预算按次扣减、sha256 检索缓存（单次命中 4 次且不扣额度）、dry-run 先预演 12 条 query；一次真实调研发起 0 次联网检索 / 0 credits，完成 4 次模型请求 / 12675 tokens，产出 4904 字符、18 条来源、32 处行内引用的简报。

**每条对该岗位的价值（面试自述，不写进简历）**：

- 「从真机报告定位并修复合成语料测不出的问题」——RAG 的典型失败不是「检索不到」，而是「检索到同名不同实体」，以及「两份来源各说一个数」。这里用标题交易所代码绑定 + 跨文档官网域名一致性做消歧，同栏目多值冲突显式标注、不替读者取舍——因为按置信度选一条会正好留下错的那个。
- 「人工核验标准答案与可回归的评测台」——评测口径是最容易糊弄的地方：人工核验标准答案、AI 语义 judge、证据句逐字校验；再用 A/B 关掉行内引用，让引用分归零而事实准确率不动，证明 fixture 满分只是流程契约分。
- 「真实检索链路与额度纪律」——检索侧工程：缓存 key 由 query / section / 条数 / depth / topic 取 sha256，命中直接返回文档、不扣额度，所以一次真实调用之后能离线反复复现同一批检索结果。

**这一版不要写**：

- 本项目是网页检索，不是向量库：不要写「召回率」「向量索引」「chunk 策略」，这三样既没实现也没测。
- 别写「引用可追溯率」：引用层明确标了不可用（换过 URL 的条目没有重抓），只写「行内引用带编号、可点回原文」。

代码位置：`capabilities/entity_guard.py`、`capabilities/conflict.py`、`docs/LIVE_SCORE.md`、`docs/LIVE_BATCH.md`、`evals/live_quality.json`、`evals/judge.py`、`evals/metrics.py`、`evals/build_golden_live.py`、`evals/build_live_report.py`、`.github/workflows/eval.yml`、`capabilities/tavily_retriever.py`、`capabilities/structured.py`、`evals/live_dryrun.py`、`evals/live_run.py`。

## 3. 后端 / 服务化（外部依赖、预算、持久化与生命周期）

**一句话定位**：把上游自带的 FastAPI `/research` 入口从旧的线性调用切到新图：每次请求独立 thread_id + SQLite checkpoint 续跑，外部调用走预算与磁盘缓存，出问题能凭落盘产物定位到具体请求。

**为什么这么排**：后端岗看三件事：外部依赖失控怎么办、进程重启会怎样、跑测试会不会偷偷花钱。所以额度纪律打头，checkpoint 与客户端生命周期居中，评测进 CI 收尾。

**可直接粘贴（三条，按此顺序）**：

- **真实检索链路与额度纪律**：接真实 Tavily + 阿里云 qwen-plus 跑通端到端：三重 opt-in 默认全关、用户额度硬上限 200 credits、进程内调用预算按次扣减、sha256 检索缓存（单次命中 4 次且不扣额度）、dry-run 先预演 12 条 query；一次真实调研发起 0 次联网检索 / 0 credits，完成 4 次模型请求 / 12675 tokens，产出 4904 字符、18 条来源、32 处行内引用的简报。
- **图编排与可恢复的人工复核（LangGraph）**：在上游线性 LangGraph 流水线（一路 `add_edge` 串到底、无分支、无 checkpoint）的基础上重构：主图精简为「检索调度 → 成稿」三段式（grounding → research → briefing），检索侧拆成 Company / Industry / Financial / News 4 张**独立编译的子图**，由编排层用 `Send` 并行派发；每张子图自带 state schema 与自闭环（检索 → 消歧 → 抽取 → 证据判定 → 不足自返工（上限 `max_retry`）→ 写段落），主图不再协调回退；报告层退化为纯拼装工，统一编号与 References。全流程落 checkpoint，成稿前可 `interrupt()` 暂停、换进程 `Command(resume=...)` 续跑。
- **人工核验标准答案与可回归的评测台**：为真实报告建人工核验标准答案（25 条事实 / 5 家公司），二次复核修订 11 条、替换 6 条打不开的原始出处；把引用判定从词法代理升级为 AI 语义批改（1 次请求 / 3435 tokens），产物显式标注非人工裁定、不作为对外指标。评测台内置 8 项指标 / 6 个评测组，A/B 关掉行内引用即让引用分归零、幻觉代理升满，而事实准确率不变——证明 fixture 满分只是流程契约分。

**每条对该岗位的价值（面试自述，不写进简历）**：

- 「真实检索链路与额度纪律」——外部依赖一律当不可信处理：三重开关是「与」关系，任一不满足直接抛 `LiveRetrievalDisabled`；`CallBudget` 在发请求前扣额度、用尽抛错不重试；缓存 key 取参数 sha256，命中不扣额度。
- 「图编排与可恢复的人工复核」——持久化选型没为了好看硬凑：异步节点下同步 `SqliteSaver` 的 `aget_tuple` 会抛 `NotImplementedError`，PostgresSaver 未实现就明确抛错。另外长驻入口每来一个请求会泄漏一个 `httpx.AsyncClient`，改成把所有权交给一次图运行、退出时 `aclose()`，并有生命周期测试盯着。
- 「人工核验标准答案与可回归的评测台」——评测进 CI：fixture 回归零外部调用，另装 socket 禁网守卫，让「测试误耗额度」在物理上不可能发生，而不是靠自觉。

**这一版不要写**：

- 不要写「高并发 / QPS / 分布式部署」：这是单机单进程的本地复现，没压测、没上线、没有多副本。
- 不要把 checkpoint 说成「分布式任务队列」：它就是 SQLite 落盘 + 线程绑定，能力边界到「跨进程续跑」为止。

代码位置：`capabilities/tavily_retriever.py`、`capabilities/structured.py`、`evals/live_dryrun.py`、`evals/live_run.py`、`graph/builder.py`、`graph/conditions.py`、`graph/subgraphs/research.py`、`graph/nodes/human_review.py`、`persistence/checkpointer.py`、`evals/judge.py`、`evals/metrics.py`、`evals/build_golden_live.py`、`evals/build_live_report.py`、`.github/workflows/eval.yml`。

## 4. 三版共用的底线

- 正文与数字只来自 `docs/RESUME.md` 与 `docs/RESUME_EVIDENCE.md`；本文只重排、不新增测量。
- 三版都不写准确率 / 幻觉率 / 引用可追溯率 / p95 延迟 / 成本单价：**未测**。
- 三版都不写「独立开发 / 从零自研 / 上线 / 甲方 / 用户量 / 提升 X%」：没有这些事实。
- 换岗位可以换顺序与解读，不能换事实；某个岗位需要的卖点这里没有，就是没有，不许补一句。

## 5. 复现与护栏

```bash
uv run python -m evals.build_resume_variants        # 重新生成本文（0 调用）
uv run pytest -q tests/test_s11_resume_variants.py  # 护栏：裸数字 / 编号存在 / 顺序真的不同
uv run python -m evals.build_resume                 # 单版长文（含十八条面试追问）
uv run python -m evals.build_resume_evidence --verify   # 逐条执行出处表里的复现命令
```

## 6. 状态

- 本文生成：**0** 次外部连接、**0** 次模型请求、**0** Tavily credits。
- 共 **3** 个岗位方向、每版 **3** 条，覆盖 **4** 个不同条目（共 4 条）。
- 面试追问清单不按岗位重写：那十八条在 `docs/RESUME.md` §3，通用。
