# 重建规划书：Orchestrator 管理的四独立 Agent 子图

> 状态：**规划中，未开始实施**。上一版 V2 已存档于 GitHub commit `0c8d4a0`（`archive:` 提交），随时可回退。
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
四张 Agent 子图：每张 = 独立 State + 独立 graph + 独立节点 + 独立 LLM 抽取链
  company_subgraph:    retrieve → extract(LLM) → entity_guard → emit
  industry_subgraph:   retrieve → extract(LLM) → competitor_scan → matrix → emit
  financial_subgraph:  retrieve → ticker_binding → extract(LLM) → number_guard → timeline → emit
  news_subgraph:       retrieve → freshness → dedup → extract(LLM) → emit
```

**与上一版的本质区别**：`agent_*` 从"research 子图里的普通节点"变成"独立编译的子图"；派发从条件边挪进真正的 `orchestrator` 节点。

---

## 4. 实施阶段（每阶段可独立验证）

| 阶段 | 内容 | 验证 |
|---|---|---|
| R0 ✅ | 建立新分支 `rebuild/orchestrator`，从存档点 `0c8d4a0` 拉出；保留旧版可随时对比 | 分支就位，已提交 |
| R1 ✅ | **Orchestrator + 四独立子图**：4 个 compiled 子图（各带独立 state schema），orchestrator 真节点 Send 派发、arbitrate 汇合 | **6 个架构测试证明**：`Node.data` 是 `CompiledStateGraph`、四套 state 不同类、条件边派发、4 路不串；全量 571 passed |
| R2 | **四套独立 state**：各子图自己的 schema + reducer，验证并行写回不覆盖 | 各 state 独立可内省 |
| R3 | **key 映射 + LLM 抽取链**：`SYSTEM_ALIYUN_APIKEY` → `DASHSCOPE_API_KEY`，每栏目一条 `with_structured_output` 链；小规模实测（限次数） | 4 栏目真实抽取成功 |
| R4 | 逐栏目差异化节点（company 消歧 / financial 时间线 / industry 竞品 / news 时效） | 每栏目独立用例 |
| R5 | 报告层适配 + 评测回归：报告文本契约、gate、A/B | 全绿，指标无回退 |
| R6 | 文档：本规划标记完成、架构图更新；**不动简历** | 文档与代码一致 |

---

## 5. 红线（继承上一版血的教训）

1. 主图 7 节点、对外 State 字段不变；
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
