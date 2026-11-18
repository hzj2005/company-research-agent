# 重建规划书：Orchestrator 管理的四独立 Agent 子图

> 状态：**R0–R3 主体完成，R4–R6 待做**。上一版 V2 已存档于 GitHub tag `v2-archive-before-rebuild`（commit `0c8d4a0`），随时可回退。
> 本版与上一版的核心区别：**架构真实优先 + 栏目内真实 LLM 抽取**。
> 规划过程中用户已就 5 个关键决策表态，见 §1。

---

## 1. 已确认的决策（用户 2026-11-17 表态）

| # | 决策点 | 用户选择 | 本规划的落实 |
|---|---|---|---|
| D1 | 核心目标 | **架构真实优先** | 必须实现 4 张独立编译子图 + Orchestrator 节点，名副其实；功能深度可次于此 |
| D2 | LLM 抽取 | **用阿里云 key 实跑** | 栏目内结构化抽取走真实 LLM；已验证 key 可用（见 §2） |
| D3 | 简历口径 | **先不管简历** | 本规划只写技术，不涉及 `RESUME*.md` |
| D4 | 子图 state | **各自定义 state** | 四张子图各有独立 state schema，不共用 |
| D5 | LLM 降级 | **LLM → 本地小模型（预留接口）→ 规则抽取** | 三级降级链：真实 LLM 优先，失败走本地小模型接口（先留空位，用户后续接入），本地模型也失败才回退规则抽取并留痕 |
| D6 | key 映射 | **代码层支持** | `config/loader.py` 把 `SYSTEM_ALIYUN_APIKEY` 加为正式候选变量 |
| D7 | 回滚开关 | **不要开关** | 代码只留新架构；旧版已在 GitHub 存档 commit `0c8d4a0`，需要就回退到那个 commit |

---

## 2. 前置验证（已完成，非假设）

- **key 连通性**：`SYSTEM_ALIYUN_APIKEY` 用 `qwen-plus` + DashScope OpenAI 兼容端点实测返回 200；不是 OpenRouter（401）。探针 `evals/probe_llm_key.py`。
- **变量名映射**：项目代码读 `DASHSCOPE_API_KEY`，用户环境变量是 `SYSTEM_ALIYUN_APIKEY`——**必须在启动层做映射**（见 §6 待确认之一）。
- **嵌套子图可行**：上一版 S1 探针 `evals/probe_nested_send.py` 已证明 compiled 子图可作为节点被子图 Send 派发（LangGraph 1.2.22）。
- **存档点**：`0c8d4a0` 保留全部上一版工作，重来不是删除。

---

## 3. 目标架构

```
主图 graph/builder.py（7 节点，对外契约不变）
  grounding → research → curate → evidence_check → [branch] → briefing
                            ↑            │
                            └── rewrite_query（自纠正）
research 节点 = Orchestrator 子图（本次真正的编排层）
  START → orchestrator ──Send(company)────→ company_subgraph   ┐
                       ──Send(industry)───→ industry_subgraph  ├→ arbitrate → END
                       ──Send(financial)──→ financial_subgraph │
                       ──Send(news)───────→ news_subgraph      ┘
主图（R3 修订，用户 2026-11-17 决策）：5 节点 = grounding → research → briefing（+可选 human_review）
  移除 curate / evidence_check —— 消歧与证据判定下沉进各子图
  rewrite_query / degrade 的回退职责也进子图（子图内自闭环，Orchestrator 不协调回退）

四张 Agent 子图：每张 = 独立 State + graph.py + nodes.py + prompts.py（四件套），自闭环：
  retrieve → 消歧(guard) → extract(LLM) → evidence(判定) → [不够自返工 ≤2轮] → write_paragraph
  write_paragraph 产出「栏目段落」= facts(claim+source_url) + 状态 + 冲突标注，**不带编号**
  company:     + entity_guard + conflict 标注
  financial:   + ticker_binding + number_guard + timeline（同轮才判冲突）
  industry:    + number_guard + classify_slots + competitor_scan + positioning
  news:        + freshness_filter + dedup_events

报告层 briefing = 纯拼装工：
  收四段 → assemble.py 统一编号 + References → Markdown
  不再自己调 LLM 抽取（避免同一文档抽两次）
```

**与上一版的本质区别**：`agent_*` 从"普通节点"变成"独立编译子图 + 自闭环任务流"；报告层从"抽+写"退化成"只拼装"；主图从 7 节点精简为 5 节点。

**R3 关键决策链（用户逐条确认）**：
1. 子图写段落、报告层只拼装；
2. 编号由拼装工统一做（子图不碰编号，避免多栏目 [1] 撞号）；
3. 消歧搬进子图（搜错人的资料在子图内就扔掉）；
4. 主图移除 curate / evidence_check；
5. 回退重检子图内自闭环（每个子图自己返工 ≤2 轮，Orchestrator 不协调）；
6. 四栏目 extract 先用通用 `SectionBrief` 抽 Fact，专用契约留 R4 规则派生；
7. 严格四件套、extract 每栏目各自实现；
8. 三级降级：LLM → 本地小模型(预留) → 规则。

---

## 4. 实施阶段（每阶段可独立验证）

| 阶段 | 内容 | 验证 |
|---|---|---|
| R0 ✅ | 建立新分支 `rebuild/orchestrator`，从存档点 `0c8d4a0` 拉出；保留旧版可随时对比 | 分支就位，已提交 |
| R1 ✅ | **Orchestrator + 四独立子图**：4 个 compiled 子图（各带独立 state schema），orchestrator 真节点 Send 派发、arbitrate 汇合 | **6 个架构测试证明**：`Node.data` 是 `CompiledStateGraph`、四套 state 不同类、条件边派发、4 路不串；全量 571 passed |
| R2 ✅ | **四套独立 state**：各子图自己的 schema + reducer，验证并行写回不覆盖 | 4 测试证明隔离；全量 575 passed |
| R3 ✅ 完成（含实跑，如实标注） | **数据流重构**：key 映射 + 四子图自闭环（检索→消歧→抽取→判定→返工→写段落）+ 主图移除 curate/evidence_check 变 5 节点 + 报告层改拼装器。三级降级链（LLM→本地小模型预留空位→规则）由共享 `extract.py` 执行，四栏目接入。 | **561 passed 全绿**；评测 gate PASS 全指标 1.0；48 个旧测试迁移；3 个降级链测试。查漏补漏：修复降级链死代码（原四栏目各写两级，现接共享三级）。**R3-live 实跑（4 次）：company/financial 真实 LLM 成功（证明链路+prompt+URL守卫），industry/news 云端 Connection error 降级到规则（证明降级链真实故障下生效）。用户确认不补跑；4 栏目真实 LLM 全成功未达成，如实标注。** |
| R4（进行中） | **四栏目差异化节点**：复用已有 capabilities 能力下沉进各子图。R4-1 Company 冲突标注 / R4-2 News 时效去重 / R4-3 Financial 时间线+数字保真 / R4-4 Industry 竞品矩阵 | 每栏目独立用例；548 测试不回归；评测 gate 保持 PASS |
| R5 | 评测回归：报告文本契约、gate、A/B | 全绿，指标无回退 |
| R6 | 文档：本规划标记完成、架构图更新；**不动简历** | 文档与代码一致 |

### R4 细化（用户 2026-11-18 确认）

**三个决策**：① `features.postprocess` 开关保留（便于 A/B）；② 冲突**同轮才判**（跨轮视为陆续补充）；③ 旧死代码（`graph/subgraphs/research.py`）本次不动。

**关键前提（已核实）**：所需算法上一版已存在于 `capabilities/`，R4 是"搬进子图 + 适配接口"，非从零实现。

| 子阶段 | 栏目 | 加什么 | 复用能力 | 验收 |
|---|---|---|---|---|
| R4-1 | Company | 冲突标注（同轮判） | `conflict.detect_conflicts` | 同轮两个取值 → 报告出现 `>` 引用块；跨轮不标 |
| R4-2 | News | 时效过滤 + 事件去重 | `postprocess.news_postprocess` | 过旧事实被过滤；同事件多来源不重复 |
| R4-3 | Financial | 融资时间线 + 数字保真 | `finance_postprocess` | 轮次按时间排序；金额必须在原文出现 |
| R4-4 | Industry | 竞品扫描 + 槽位分类 + 对比矩阵 | `postprocess.industry_postprocess` | 竞品分层正确；矩阵不生成"谁更强"评价 |

**实施顺序**：由易到难 R4-1 → R4-2 → R4-3 → R4-4，每步独立验证后再进下一步。

---

## 5. 红线（继承上一版血的教训）

1. **主图由用户决策改为 5 节点**（R3 移除 curate/evidence_check，消歧与判定下沉子图）——这是对旧红线"7 节点不变"的**显式变更**，已获用户确认；对外 State 字段尽量保持兼容；
2. 每条结论带 source_url，查不到就拒答；
3. 不生成推断性结论（重要性/情感/定位点评）；
4. 不写未测指标进简历（本版不碰简历，但代码/文档同样遵守）；
5. **汇报必须区分"设计稿"与"已实现"**——上一版最大的教训就是这句没做到，拖到用户追问才发现架构降级。

---

## 6. 决策已全部确认（无待定项）

四个问题用户已全部回答，落实见 §1 的 D5/D6/D7。**补充一条护栏决策**：真实 LLM 调用不设人为次数上限，但沿用项目既有的额度纪律（不无脑重跑、实测结果留档、探针用 `max_tokens=1` 最小请求）——因为 key 已实测可用，且用户明确要"实跑"。

降级链的具体语义（D5）：
```
栏目抽取 → ① 真实 LLM（DashScope / qwen-plus）
        → ② 失败：本地小模型接口（预留 LocalModelExtractor 空实现，后续接入）
        → ③ 本地模型也未接入/失败：规则抽取 + review_notes 留痕降级原因
```
注意：当前 ② 是空位，所以现阶段实际会走到 ③，但接口形态按 ② 设计，将来接入本地模型时无需改调用方。

---

**下一步**：开始 R0/R1。每个阶段完成都拿代码对照本规划逐条核，绝不再出现"规划写了、实现悄悄降级、拖到用户追问才发现"的情况。
