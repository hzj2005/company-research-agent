# 项目方案 V2：Orchestrator 管理的四 Agent 精细化调研

> **状态：设计稿，尚未实施。** 本文描述的是目标架构，不是当前代码事实。
> 当前仓库仍是 V1 实现：4 个 analyst 由同一个 `make_analyst_node` 工厂生成（`graph/subgraphs/research.py:66-95`），靠 `active_section` 区分，只有 query hint 不同（`capabilities/retrieval.py:47-52`）。本文所有"目标/将"字样的能力均未落地，实施前不得对外声称已实现。
> V1 设计依据见 `docs/PROJECT_PLAN.md`；编码规范见仓库根 `AGENT.md`。
> 制定日期：2026-11-17

---

## 1. 为什么要做 V2

V1 解决了「可溯源 + 自纠正 + 可回归评测」，但四个栏目的处理逻辑是**同构**的：同一份 prompt、同一组工具、同一套契约，只有检索 topic 不同。这在工程上只是「四个并行分支」，不是「四个各司其职的 Agent」。

V2 的目标是把「并行分支」升级为「**一个 Orchestrator 统一管理四个专职 Agent**」，每个 Agent 是一张独立的 LangGraph 状态图，有自己不同的任务流、状态和差异化处理节点。

### 1.1 归因声明（继续贯穿）

- 本项目是**基于 `guy-hartstein/company-research-agent`（Apache-2.0）二次开发**，保留 LICENSE、版权声明、fork 来源与 commit 历史。
- V2 的多 Agent 改造是本次新增工作，但不得写成「从零自研」。
- 原版已有能力（四路并行检索、Tavily 筛选、PDF 导出、SSE 进度）不计入 V2 功劳。

---

## 2. 目标架构

### 2.1 一句话

对外仍只有一类任务「公司调研」；内部由**一个 Orchestrator** 派发到**四张独立子图**，分别精细化处理公司、行业、财务、新闻四个栏目。

### 2.2 分层与位置（关键）

```
UI / FastAPI（不动）
        ↓
主图 graph/builder.py         ← 仍 7 节点，research 节点 = Orchestrator 子图
        ↓
Orchestrator 子图             ← 唯一编排层：dispatch / Send / arbitrate / 回退
        ↓
4 张独立 Agent 子图           ← company / industry / financial / news
   每张 = state.py + graph.py + nodes.py + prompts.py
        ↓
能力层 capabilities/          ← retrieval / entity_guard / conflict / structured ...
        ↓
持久化 + 评测层（不动）
```

**Orchestrator 的位置**：放在 `research` 节点内部，**不是最外层**。项目对外只有一类任务，最外层没有第二个任务可路由，放在那里就是「只分派不执行」的空壳（EduAgent 的教训）。放在子图层级，它才真的在给四张子图派活。

**Orchestrator 的职责边界**：只做派发、仲裁和回退协调，**不产出报告内容**。

### 2.3 与 V1 的兼容契约（不可破）

| 约束 | 依据 |
|---|---|
| 主图仍 7 节点，`research` 节点名不变 | `tests/test_s4_subgraph.py:96-100` 精确断言 7 节点；CLI 轨迹依赖节点名 |
| 对外 State 字段不变 | 子图仍只输出四类文档，上层无感 |
| 不用节点内 `asyncio.gather` 代替图并行 | `AGENT.md` 6.4 明令禁止 |
| `docs/RESUME*.md` 是渲染产物 | 改模板后重生成，手改会被 `tests/test_s9_resume.py:40` 打红 |

---

## 3. Orchestrator 设计

| 环节 | 实现方式 | 状态 |
|---|---|---|
| 派发 | `dispatch` 节点读 `sections_to_research` 白名单，用 `Send` 派发到 4 个子图 | 复用 `research.py:36-55` 的 `Send` 逻辑，需适配嵌套子图 |
| 仲裁 | `arbitrate` 节点做跨栏冲突标注 + 引用编号统一 | 新增，复用 `capabilities/conflict.py` 的模式 |
| 回退 | 证据不足时只重派白名单内、证据不足的栏目，最多 2 轮 | 沿用 V1 的 `sections_to_research` 白名单机制 |
| 留痕 | dispatch 决策写入 State，可追溯本轮派发范围 | 新增 |

### 3.1 实施前提：嵌套 Send 探针

LangGraph 子图嵌子图 + `Send` 派发到嵌套子图节点，本仓库尚未实测（`AGENT.md` 6.7 只验证了一层子图继承 checkpointer）。**实施第一步必须先写探针验证**，失败则退回「4 个平铺节点 + 内部条件链」的降级方案。

> **S1 探针结果（2026-11-17）：PASS，V2 架构成立，无需降级。**
> 探针 `evals/probe_nested_send.py`：外层子图用 `Send` 派发到 4 个 compiled 内层子图节点，状态传递与 reducer 汇总均正常。
> 实测输出：`['dispatch:4', 'inner:company', 'inner:industry', 'inner:financial', 'inner:news']`。
> 环境：LangGraph 1.2.22 / langgraph-checkpoint 4.3.2，0 网络 0 模型调用。

---

## 4. 四个 Agent 子图规格

每张子图含四件套：`state.py`（局部 State）、`graph.py`（拓扑）、`nodes.py`（节点实现）、`prompts.py`（独立 prompt）。

| Agent | 目标工作流 | 差异化处理节点 | 能力来源 | 分支 |
|---|---|---|---|---|
| Company | retrieve → guard → extract → conflict → evidence → emit（6 节点） | `entity_guard`、`detect_conflicts` | 现有函数，从主图 `curate`/`report` 下沉 | 消歧后 <2 条 → 回退；用尽 2 轮 → 拒答 |
| Industry | retrieve → extract → number_guard → classify_slots → competitor_scan → positioning → evidence → emit（8 节点） | 框架归类 + 竞品分层 + 事实对比矩阵 | 全新增（复用 `with_structured_output`） | 市场规模多数字 → 标口径差异；无依据 → 回退重检 |
| Financial | retrieve → ticker_binding → entity_guard → finance_extract → number_guard → timeline_sort → conflict → evidence → emit（9 节点） | `ticker_binding` + 财务专用契约 + 数字保真 + 时间线 | 前两项现有下沉；后三项纯新增 | 串号拒答；组内金额冲突标注 |
| News | retrieve → freshness_filter → dedup_events → extract → evidence → emit（6 节点） | 时效过滤 + 事件去重 | 全新增 | 无有效新闻且未超 2 轮 → 回退重检 |

★ = 纯新增能力。**带 ★ 的节点多数还没实现**，这不是「把现有 4 节点改名」，而是真重构。

### 4.1 各任务流详细设计

> 设计稿，未实施。以下工作流按「每条图拓扑不同」设计，不是同一骨架换节点名。

#### 4.1.1 Company 公司概况（已定稿）

**核心风险**：同名不同实体混入 + 同一事实多来源打架。真机踩坑：Notion VTec Berhad (0083.KL) 占满财务位、Notion 成立年份 2013/2014 冲突。

**拓扑（6 节点）**：

```
retrieve → guard → extract → conflict → evidence → emit
              ↑                            │
              └──── 回退重检（<2 条 / 不足且未超 2 轮）────┘
                                           └── 用尽 2 轮 → 拒答
```

| 节点 | 职责 | 能力来源 |
|---|---|---|
| `retrieve` | 检索 company 栏目文档 | 现有 `fetch_company_documents` |
| `guard` | 文档级实体消歧，挡同名异实体 | `entity_guard.filter_docs`（`collect.py:46` 下沉） |
| `extract` | LCEL + `with_structured_output` 抽 facts | 现有 `extract_section_brief`（`structured.py:108`） |
| `conflict` | 事实级冲突标注，**只标不改写** | `detect_conflicts`（`report.py:160` 下沉） |
| `evidence` | 证据判定（≥2 条） | 现有 `evidence_check`（`decide.py:19`） |
| `emit` | 写 `company_data` | — |

**三条关键设计**：

1. **消歧在抽取前**：脏来源一旦进了 facts，冲突检测就在比较两个假公司的年份，越比越乱。纯规则、0 模型调用。
2. **冲突只标注不裁决**：真机里 score 0.77 的 2014 是错的、0.72 的 2013 才对；按置信度选反而选错。两句都保留，判断权留给读者（`conflict.py:9-12`）。
3. **全灭护栏**：消歧把栏目清空时全部放行并留痕（`entity_guard.py:335-340`），防止误杀带法域后缀的正经公司。

**guard 实现要点**（纯正则 + 集合查表，0 LLM / 0 网络）：

- `ticker_binding`（`:92`）：标题命中 `公司名 + 扩展名 + (数字.字母)` 且扩展名含法域后缀（Berhad/Bhd/GmbH/AG…）→ 拒。
- `listing_page`（`:287-298`）：扩展名合法域后缀且正文命中 ≥2 个行情词（market cap / shares outstanding…）→ 拒。
- `find_incoherent`（`:194`）：跨文档官网域名无交集且成立年份与多数派不同 → 拒少数派。
- 通用后缀（Inc/Ltd/Labs）放行——`Notion Labs, Inc.` 是 Notion 自己的实体名（`:51-56`）。

**分支**：消歧后 <2 条或证据不足且未超 2 轮 → 回退重检；用尽 2 轮 → 栏目拒答。

**唯一新增点**：把被消歧砍掉的来源理由作为负例喂回 `extract` 的 prompt，防止 LLM 又被被砍事实捡回来。当前代码没有。

**Agent 性说明（面试必须诚实）**：本流 6 个节点中只有 `extract` 是一次固定 LCEL 链调用，其余是工具/规则/计数/赋值；不是 ReAct 式自主 Agent。Agent 性体现在图级——有状态、条件边、回退闭环，以及 Orchestrator 按需派发。

**例子**：调研 Notion → 搜回 3 篇 → guard 挡掉 `Notion VTec Berhad (0083.KL)`（法域后缀 + 代码，异实体）→ 剩 2 篇抽事实（成立于 2013 / 总部旧金山）→ conflict 发现 2013 与 2014 两个说法，都保留并标注 → 证据够 2 条 → 写入公司概况。

#### 4.1.2 Financial 财务概况（已定稿）

**核心风险**：同名上市公司行情页混入（真机 Notion VTec 一篇拆出 10 条 fact 占满栏目）+ 财务数字幻觉 + 把不同轮次误判成冲突。财务数据带单位、带时点、带数值，不能复用通用 `Fact` 契约。

**代码事实**：`contracts.py:21,32` 只有通用 `Fact` + `SectionBrief`；V1 规划里的 `FundingRound`（轮次/金额/投资方）**从未实现**——这正是财务精细化的落点。

**拓扑（9 节点）**：

```
retrieve → ticker_binding → entity_guard → finance_extract → number_guard
         → timeline_sort → conflict → evidence → emit
```

| 节点 | 职责 | 能力来源 |
|---|---|---|
| `retrieve` | 检索 finance topic 文档 | 现有（`settings.yaml:42`） |
| `ticker_binding` | 标题级：公司名+法域后缀+股票代码 → 拒 | 现有规则（`entity_guard.py:92`） |
| `entity_guard` | 跨文档级：官网域名无交集且成立年份少数派 → 拒 | 现有 `filter_docs` |
| `finance_extract` | 用**专用契约** `FundingRound`/`Revenue` 抽取 | **新增契约** |
| `number_guard` | 数字保真：抽出的金额/日期必须在原文逐字可查 | **新增** |
| `timeline_sort` | 融资按轮次排成时间线 | **新增** |
| `conflict` | 只在**同一轮次组内**查金额冲突 | 复用 `detect_conflicts` 思路，改分组逻辑 |
| `evidence` | 证据判定 | 现有 |
| `emit` | 写 `financial_data` | — |

**两道实体门的边界**：`entity_guard.filter_docs` 内部本来就会调 `ticker_binding`（`entity_guard.py:275`）。这里拆成两个节点是为了**独立开关与留痕**，不是重复调用两次——实施时 `ticker_binding` 节点只做单篇标题判定，`entity_guard` 节点关闭重复的单篇规则、只跑跨文档一致性。

**与 Company 最本质的区别（面试拉开差距的点）**：Company 见两个不同取值就标"冲突、只标不改"；Financial 见两个不同融资金额**不急着判冲突**——A 轮 500 万、B 轮 2000 万是时间序列不是矛盾。`timeline_sort` 先按轮次分组，`conflict` 只在**同一轮内部**查金额打架。

**分支**：串号 → 栏目拒答；同轮金额冲突 → 标注待核；证据不足未超 2 轮 → 回退重检。

**例子**：搜回"A 轮 500 万（2021）""B 轮 2000 万（2023）"→ 数字核对无误 → 排成 A→B 时间线，不报冲突；若又来"A 轮 800 万"→ 同组金额冲突 → 标注待核。

**代价**：9 节点，`FundingRound` 契约、`number_guard`、`timeline_sort` 全新增，fixture stub 要为财务契约单独写。

#### 4.1.3 Industry 行业概况（已定稿）

**核心风险**：散落事实堆砌无结构、竞品混淆、多来源市场规模数字被误判成冲突。行业栏目的专业性在于**框架化归类 + 竞品分层 + 相对定位**，而非单纯抽事实。

**拓扑（8 节点）**：

```
retrieve → extract → number_guard → classify_slots → competitor_scan
         → positioning → evidence → emit
```

| 节点 | 职责 | 能力来源 |
|---|---|---|
| `retrieve` | 检索 industry topic 文档 | 现有（`settings.yaml:49`） |
| `extract` | 抽行业事实 | 现有 `extract_section_brief` |
| `number_guard` | 市场数字保真（同 Financial 逻辑） | 新增（复用财务的校验思路） |
| `classify_slots` | facts 归类到固定框架槽位：市场规模 / 增速 / 竞争格局 / 技术趋势 / 挑战 | **新增**，用 `with_structured_output` |
| `competitor_scan` | 竞品**分层**：直接 / 间接替代 / 相邻玩家 + 别名归一 | **新增**，需别名表 |
| `positioning` | 构建**事实对比矩阵**（见下方设计约束） | **新增** |
| `evidence` | 证据判定 | 现有 |
| `emit` | 写 `industry_data` | — |

**三个栏目三种冲突逻辑（面试拉开差距的点）**：

- Company：两个取值不同 → 标冲突、只标不改。
- Financial：不同融资轮次 → 时间序列；只在同轮组内查冲突。
- **Industry**：Gartner 说市场规模 50 亿、IDC 说 200 亿 → **既不是冲突也不是时间序列，是口径差异**（一个算协作文档、一个算全部生产力软件）→ 标"口径差异"，各自保留来源与统计范围，**不替读者合并**。

**关键设计约束：positioning 必须可溯源，禁止生成推断观点。**

最初设计是让模型写一段"该公司在赛道的位置"分析，但这会破坏项目"每条结论可对回原文"的红线——推断观点没有 source_url，judge 会判无引用。改造方案：

1. 固定对比维度：目标客户 / 核心功能 / 部署方式 / 定价模式。
2. 逐格从**已有 facts** 里挑对应原文搬运，**不生成新判断**。
3. 每格带 `source_url`，指向原文。
4. 无依据的格子写"无公开依据"（复用现有 degrade 话术），不脑补。

输出是对比矩阵而非散文：

| 维度 | Notion | Obsidian |
|---|---|---|
| 部署 | 云端协作 [url1] | 本地 Markdown [url2] |
| 定价 | 团队订阅 [url3] | 个人免费 [url4] |

本质是把分析从「模型下结论」换成「模型整理证据」——保留对比价值，全程可溯源。

**例子**：搜回行业文档 → extract 抽事实 → number_guard 核对数字 → classify_slots 归入"规模 50 亿（Gartner 口径）/ 增速 20% / 挑战：同质化" → competitor_scan 分层：Obsidian=直接、Word=替代 → positioning 拼出事实对比矩阵 → 写入行业概况。若某维度无依据 → 该格写"无公开依据"。

**代价**：8 节点，`classify_slots` / `competitor_scan` / `positioning` 全新增，`number_guard` 复用财务版；竞品别名表需人工维护；报告渲染需支持表格（`report.py` 要改）；fixture stub 要按新契约重写。

#### 4.1.4 News 新闻动态（已定稿，可实施版）

**核心风险**：新闻的价值在**时效**和**不重复**——前三条栏目解决"真假"，News 解决"新旧"和"重复"。

**拓扑（6 节点）**：

```
retrieve → freshness_filter → dedup_events → extract → evidence → emit
```

| 节点 | 职责 | 能力来源 |
|---|---|---|
| `retrieve` | 检索 news topic 文档 | 现有（`settings.yaml:43`） |
| `freshness_filter` | 时效过滤，剔除过期新闻 | **新增**，日期来源见下方约束 |
| `dedup_events` | 事件去重：同一事件多家报道合并成一条 | **新增** |
| `extract` | 抽新闻事实 | 现有 `extract_section_brief` |
| `evidence` | 证据判定 | 现有 |
| `emit` | 写 `news_data` | — |

**日期来源约束（卡点）**：fixture 文档只有 `content/score/source/title/url`，**无 `published_at` 字段**。可实施方案是从 `content` 正则抠日期，并标注"推断日期"（不伪装成结构化字段）。不采用改检索层 + 重生成 fixture 的方案（成本高、动得多）。

**为什么不上一版更复杂的方案**（记录决策，避免反复）：
- `source_tier` 来源分层（高可行，纯域名规则）→ 暂不纳入本版，列为可选扩展。
- 多源交叉印证（同一事件 ≥2 家报道→标"多源确认"）→ **设计上最值钱，但当前 fixture 只有 3 case、每栏 2 文档，可能根本凑不出"同一事件多来源"，评测无法验证**。列为"待数据支撑的扩展"，不写进当前实施范围。
- 重要性排序 / 情感判断 → **否决**：推断性结论无 source_url，破坏"每条结论可对回原文"红线，与 Industry.positioning 同病。

**分支**：无有效新闻且未超 2 轮 → 回退重检；用尽 2 轮 → 栏目拒答。

**例子**：搜回 5 篇 → freshness_filter 剔除 2 篇旧闻（从正文抠出的日期判定）→ 剩 3 篇里 2 篇讲同一融资事件 → dedup_events 合并成一条 → 抽事实 → 写入新闻动态。

**面试话术**：
> 新闻栏目的差异化是时效过滤和事件去重——同一件事多家报道合并成一条。我没有做重要性排序或情感判断，因为那些是推断性结论、无法溯源，会破坏项目每条结论可对回原文的红线。多源交叉印证设计上有价值，但当前样本量撑不起来，所以我按可验证的范围落地。

**代价**：4 个新节点中的 `freshness_filter`（日期推断）和 `dedup_events`（事件判定）都需新写；日期推断不准，须在输出中标注。

---

## 5. 目录结构（目标）

```
graph/
  builder.py                    # 主图，不动
  orchestrator.py               # 新增：Orchestrator 编排子图
  agents/
    company/{state,graph,nodes,prompts}.py
    industry/{state,graph,nodes,prompts}.py
    financial/{state,graph,nodes,prompts}.py
    news/{state,graph,nodes,prompts}.py
  subgraphs/research.py         # 改造为派发入口（或由 orchestrator.py 取代）
capabilities/                   # 现有能力，按需下沉到各 Agent
```

回滚开关：`config/settings.yaml` 增加 `features.multi_agent: false`，关闭时走旧的 `analyst` 单节点路径。

> **S4 实施调整（与设计稿的差异，须如实记录）**：
> 1. 设计稿里 Company 的 `conflict` 节点、Financial 的 `finance_extract`/`number_guard`/`timeline_sort` 节点**本阶段未实现**——它们依赖结构化 facts 下沉到子图，而当前抽取仍在 briefing 阶段。强行对文档正文做冲突检测是无效的（槽位正则针对英文 fact、fixture 正文是中文整段）。留到 S5 抽取链下沉后再接。
> 2. Financial 两道门用 `EntityGuard.judge` + `find_incoherent` 手工分工，而非直接两次 `filter_docs`——因为 `filter_docs` 内部已含单篇 ticker 判定，重复调用会跑两遍。
> 3. 因此**当前"多 Agent"的差异化只在检索阶段的实体拦截**，尚未覆盖设计稿承诺的事实抽取/冲突标注/时间线。对外表述必须限定在这个范围。

> **S5 实施调整（后处理层，非抽取链下沉）**：设计稿要求把抽取链下沉到子图、各 Agent 内部做事实级加工。实测评估后改为**在 briefing 之后加可选后处理层**——原因：抽取链下沉要重写 `_render_structured`、报告结构和几乎全部测试断言，风险与收益不匹配；后处理层在保留可溯源红线（只搬运已有 facts、每格带 source_url、无依据记 missing）的前提下，以零报告漂移（逐字节一致）拿到行业/新闻专项能力。代价：竞品识别依赖词表（词表外名字不识别）、时效日期从正文推断（不精确）、能力落在后处理而非子图内部。对外表述须说明这一架构选择。

> **S6 实施说明（arbitrate 能力边界）**：设计稿写"跨栏冲突标注 + 引用编号统一"。实际只做了前者，且只覆盖**成立年份一个槽位**的中文正则比对——因为 `capabilities.conflict.detect_conflicts` 的槽位正则是英文的（founded/headquartered），对本项目中文正文空跑（S4 已踩坑）。引用编号统一本就在报告层 `_render_structured` 做（`norm_index`），子图层无需重复。对外说"仲裁节点做跨栏年份一致性检查"，不要说"完整的跨栏冲突仲裁"。另：dispatch 留痕在关闭 multi_agent 时也会写一条（不影响报告与评测），严格说回滚路径并非零留痕变化，如实记录。

**S6 复查补记**：端到端实测抓到 arbitrate 一个真 bug——初版用"所有年份集合 >1"判跨栏冲突，但 fixture 的 2013/2014 都在 company **同栏**，被误报成跨栏冲突（职责越界，同栏冲突归报告层 detect_conflicts）。已修为"至少两个栏目都有年份且取值不一致"，并加 `test_arbitrate_ignores_same_section_conflict` 锁住边界。修复后端到端误报为 0、553 passed。教训：单测只覆盖了跨栏正例，没覆盖同栏反例，端到端才暴露。

**S5 复查补记**：单测之外另做了端到端溯源验证——开启后竞品证据、对比矩阵每格、新闻事件来源的 URL **全部可在报告 References 中找到**（16 条引用），无编造。但要注意**覆盖度低**：当前 fixture 下对比矩阵只有 2 格、13 个 `(维度,主体)` 记进 missing——这是"严格不脑补"的必然结果，不是 bug，但对外不能把对比矩阵说成"完整竞品对比"，应说"只填有原文依据的格，其余标无公开依据"。

---

## 6. 实施清单（从当前代码到 V2）

### 6.0 顺序原则

**先探针 → 再定素材 → 再代码 → 再测试 → 最后评测。** 理由：

- 探针最先跑，因为嵌套 `Send` 不成立时整个架构要降级，后面全白做（S1 已 PASS）；
- 测试跟着代码改，先改测试会一片红、无法验证（这里修正 V1 文档"先写测试"的通用说法——新契约/新节点场景下必须先有实现）；
- **素材不必抢在代码前**：`golden.jsonl` 是从 fixture 派生的（`evals/build_golden.py`，文件头 `generated_by`/`source_fixture`），23 条 claim 的 `source_content` 来自 fixture 文档，`expected_research_runs`/`first_round_insufficient` 依赖 rounds 结构。所以**改 fixture = 改基线**，必须和重生成 golden、重存基线捆绑成一个原子阶段，否则基线静默失效。

每阶段一个 commit、可独立回滚。

**S2 执行教训（已并入阶段定义）**：改 fixture 的连锁反应不止 golden 和 scorecard，还有一批测试硬编码了 fixture 派生的数值（报告长度、claim 数）。所以 S2 扩成四步原子阶段，第四步把魔数断言改成结构/派生断言——否则扩数据必然让测试变红，且这种红是假阳性。

**S2 复查补记（2026-11-17）**：
- `test_reject_sections_changes_only_that_section` 曾一度改成 `"近期发布" not in 新闻段`——这是**废话断言**：新 fixture 新闻正文已无该字样，恒为真。已改为"新闻段只剩 ABSTAIN 行、无任何残留事实行"，并做了反向验证（人为塞回事实行，断言能抓到）。教训：改断言必须验证它在"坏情况"下会失败，不能只看绿。
- **发现一个既有测试隔离缺陷（非本次引入）**：`tests/test_s8_golden_live.py` 的 autouse fixture 直接调 `build_golden_live.main()` 写生产文件 `evals/golden_live.jsonl`，而该脚本用 `date.today()` 生成 `generated_at`——每次 `pytest` 都把人工核验文件的生成日期覆盖成当天。**已修（方案 A）**：`main(output: Path | None = None)` 加输出路径参数（默认写生产路径保持 CLI 行为）；测试用 `tmp_path_factory` 建临时目录，`main(tmp)` 生成、`_rows(tmp)`/`load_golden(tmp)` 读取，彻底不碰生产文件。**验证**：跑前跑后 `golden_live.jsonl` 哈希完全一致（`6ca19d0`），11 个 S8 用例 + 全量 565 passed。从此不用手动 `git checkout` 还原。

### 6.1 阶段表

| 阶段 | 内容 | 涉及文件 / 节点 | 验证 |
|---|---|---|---|
| **S0 基线留档** ✅ 已完成 | 跑通现状，存下 scorecard 和 7 节点断言结果 | `docs/BASELINE_V2_BEFORE.json` | 507 passed / 13 skipped；scorecard gate PASS（fact_accuracy=1.0、citation=1.0、abstain=1.0、hallucination=0），0 外部调用 |
| **S1 嵌套 Send 探针** ✅ 已完成 | 验证子图用 `Send` 派发到嵌套子图节点 | `evals/probe_nested_send.py`（已建） | **PASS** — 派发/传参/reducer 汇总均正常，V2 成立无需降级 |
| **S2 素材扩充（原子阶段，不可拆）** ✅ 已完成 | ① 扩 fixture（Notion 每栏 4 篇：多轮融资/冲突年份/带日期新闻/竞品与双口径）；② 重生成 golden（claim 23→31）；③ 重存基线；④ **同步测试断言**——把写死 `len(report)==772/779`、`claims==23` 的断言改成结构断言/派生计数（`conftest.assert_report_shape`）。四步必须一次做完 | `evals/fixtures/tavily_responses.json`、`evals/golden.jsonl`、`docs/BASELINE_V2_BEFORE.json`、`tests/{conftest,s5_entrypoints,s5_offline,s6_hitl,s7_eval}.py` | golden 与 fixture 同步（`build_golden --check` PASS）；scorecard gate PASS；pytest 520 passed |
| **S3 新契约落地** ✅ 已完成 | 新增 5 个契约：`FundingRound`/`RevenueInfo`（财务）、`Competitor`/`MatrixCell`/`ComparisonMatrix`（行业）。**保守策略：只定义 + 单测，不切换 stub、不改报告渲染**，接入留给 S4/S5 | `graph/contracts.py`（+`Literal` 导入）、`tests/test_s3_contracts.py` | 8 个契约用例通过；全量 528 passed 无回归 |
| **S4 先做 Company + Financial** ✅ 主体完成 | 加 `features.multi_agent` 开关；子图派发按开关走 4 具名节点或旧单 analyst。Company 节点接文档级消歧、Financial 接两道实体门（`judge`+`find_incoherent`，避免与 `filter_docs` 重复跑 ticker）。Industry/News 暂用基础节点（S5 再差异化） | `graph/agents/{company,financial,base}.py`、`graph/subgraphs/research.py`、`config/{settings.yaml,loader.py}`、`tests/test_s4_multi_agent.py` | 7 个新用例通过；开启模式端到端跑通；全量 535 passed；主图 7 节点不变 |
| **S5 Industry + News 差异化** ✅ 完成后处理版 | 采用**后处理层**（非抽取链下沉）：新增 `capabilities/postprocess.py`，在 briefing 之后按 `features.postprocess` 开关对已抽取 facts 做行业竞品识别/框架归类/事实对比矩阵、新闻时效标注/事件去重；写入 State 新字段 `postprocess`，**不改报告文本** | `capabilities/postprocess.py`、`graph/nodes/report.py`、`graph/state.py`、`config/*`、`tests/test_s5_postprocess.py` | 10 用例通过；报告逐字节一致、评测 gate PASS；全量 545 passed |
| **S6 Orchestrator 显式化** ✅ 主体完成 | dispatch 从空占位改成读白名单 + 写决策留痕（派谁/是否回退/轮次）；新增 `arbitrate` 仲裁节点，multi_agent 模式下 4 路真汇合后做跨栏年份冲突标注（只标不改）。关闭模式无 arbitrate，保留回滚。**S4 时的 `test_s4_subgraph.py:81,88` 断言已在 S4 同步过**；主图 7 节点断言不动 | `graph/subgraphs/research.py`、`graph/agents/arbitrate.py`、`tests/test_s6_orchestrator.py` | 7 用例通过；552 passed；开启模式评测 gate PASS |
| **S7 文档与评测回归** ✅ 已完成 | **未改简历文档**——V2 默认全关、属设计稿，写进简历就是"未实施当已实现"，与项目红线冲突；V1 事实仍成立。只验证渲染一致性（test_s9 17 + test_s11 14 passed、39/39 证据复现）+ 重跑 scorecard | `docs/SCORECARD_FINAL.json` | 受保护指标（fact/citation/abstain/hallucination）与 S0 基线完全一致；gate PASS |

### 6.2 新增节点与契约总账

| 栏目 | 新增节点 | 新增契约 |
|---|---|---|
| Company | 负例喂回（1） | 无（复用 `SectionBrief`） |
| Financial | `finance_extract`、`number_guard`、`timeline_sort`（3） | `FundingRound` / `Revenue` |
| Industry | `classify_slots`、`competitor_scan`、`positioning`（3） | `CompetitorList`、对比矩阵 |
| News | `freshness_filter`、`dedup_events`（2） | 无（含推断日期标记字段） |

合计 **9 个新增节点、4 类新契约**——这是"差一整轮重构"的具体含义。

### 6.3 回滚机制

`config/settings.yaml` 加 `features.multi_agent: false`：关闭时 `research` 节点走旧的 `analyst` 单节点路径，V1 全流程原样可用。任何阶段出问题，改一个开关回退，不必 revert commit。

---

## 7. 红线

- 主图节点数不变、对外 State 字段不变。
- 不用节点内 `gather` 代替图并行。
- 不写任何未测指标（准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本）。
- fixture stub 的 `confidence` 仍来自文档 `score`；live 三重 opt-in 与额度护栏不动。
- 本文与四张子图均为**设计稿**，实施前不得在简历或对外场合表述为已实现。

---

## 8. 面试口径（设计版，实施前使用）

> 项目用一个 Orchestrator 统一管理四个专职 Agent，每个 Agent 是一张独立的 LangGraph 子图、有自己的状态机和任务流，分别精细化处理公司、行业、财务、新闻四个栏目。Orchestrator 只做派发、仲裁和回退协调，不产出报告内容。它放在 research 子图内部，主图 7 节点和对外契约不变，因此改造可回归、可回滚。

**注意**：以上口径描述的是**目标架构**。被问到实现进度时，如实说明当前处于设计/实施阶段。

---

## 9. V2 实施收尾状态（2026-11-17）

S0–S7 全部完成。当前落地范围与边界：

| 项 | 状态 |
|---|---|
| 主图 7 节点 / 对外 State / 报告文本 | **完全不变**（V1 基线逐字节一致） |
| `multi_agent` / `postprocess` 开关 | 新增，默认 **false**（回滚路径） |
| 4 个具名栏目节点 + 2 道实体门 | 已实现，开启开关生效 |
| 行业竞品识别 / 对比矩阵、新闻时效/事件去重 | 已实现为**后处理层**（非子图内部） |
| Orchestrator dispatch 留痕 + arbitrate 跨栏年份检查 | 已实现，arbitrate 只覆盖一个槽位 |
| 财务 4 能力（数字保真 / 时间线 / 同轮冲突 / FundingRound） | **已实现为规则后处理**（`capabilities/finance_postprocess.py`），非 LLM 抽取；默认关开关 |
| 简历 `RESUME*.md` | **未改**（V2 未实施完，写入简历违反红线） |

**最终验证（2026-11-17 整体体检后）**：pytest **565 passed**；multi_agent × postprocess **四种开关组合评测 gate 全 PASS**；受保护指标与 `BASELINE_V2_BEFORE.json` 一致；39/39 简历证据可复现；0 外部调用；golden 与 fixture 同步；`golden_live.jsonl` 跑测试前后哈希不变。

**基线文件说明（避免歧义）**：`docs/BASELINE_V2_BEFORE.json` 在 S2 扩数据后被**覆盖重存**，因此它记录的是"S2 后 / V2 代码改造前"的 31-claim 基线，**不是 S0 最初的 23-claim 原始基线**——后者未单独留档（S2 原子阶段直接覆盖了同名文件）。文中"与基线一致"均指这份 S2 后基线。其 `inputs_sha256` 对应加 `multi_agent`/`postprocess` 开关前的 settings，与最终 scorecard 的指纹不同是**预期**（配置新增了开关字段），质量指标比对不受影响。

**收尾补记（2026-11-17 竞品句式抽取，方案 A）**：用户问后处理天花板（竞品靠词表/日期靠推断/矩阵覆盖低）的解决方案。根因是通用 `Fact` 只有 `claim` 文本、无结构化槽位。方案 B（LLM 抽取）需模型 key，用户环境变量只有 `TAVILY_API_KEY` 与 `SYSTEM_ALIYUN_APIKEY`；评估后选 A（规则填专用契约、零外部调用）。实现：`postprocess.py` 新增竞品句式抽取（`竞品包括 X 与 Y` / `对标 X`），词表外但句式明确的名字也能识别，`Competitor` 契约加 `tier_inferred` 字段把推断分层显式留痕（不伪装成有据标注）。防幻觉红线保留：无句式、无依据时不生成竞品（`test_unknown_name_is_not_invented_as_competitor` 仍通过）。**报告逐字节一致、评测 gate PASS、全量 565 passed**。**诚实边界**：日期靠推断、矩阵覆盖低仍在（受样本与契约限制，无真实数据前不改）；句式抽取仍是规则，措辞变化会漏。

**收尾补记（2026-11-17 财务 4 能力）**：最初因"抽取链下沉风险大"放弃了财务专用节点。复查发现前提判断过重——4 个节点里只有 `finance_extract` 真需要 LLM，其余 3 个用正则即可，且 fixture 财务文档的金额/年份/轮次实测都能规则抠出。于是新增 `capabilities/finance_postprocess.py`，用纯规则实现全部 4 项（含 B2 方案：规则填 S3 已定义的 `FundingRound` 契约，绕开 fixture stub 写死 `SectionBrief` 的限制）。接入既有后处理层、默认关开关、报告逐字节一致。关键正确性：不同轮次金额不同 = 时间线不判冲突；"融资 2 亿、估值 100 亿"只取融资额；金额必须原样在原文出现否则标注 `money_not_in_source`。**诚实边界**：这是规则实现，不是 LLM 结构化抽取；复杂表述（如"融资超亿美元"无具体数字）抠不到，live 真实语料下覆盖会下降。

**对外表述底线**：这是"按 V2 设计做了一部分、默认关闭、可回滚"的工程改造，不是"四个完整专项 Agent 已落地"。被问到细节按各阶段"实施说明"如实回答。
