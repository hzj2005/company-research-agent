# 对话式意图路由（R8）规划

> 状态：**P1 已实施（2026-11-18），P2–P6 待做**。决策日期 2026-11-18。

## 1. 目标

用户用自然语言说一句话（如「帮我看看 Notion 最近的融资和新闻」），系统：

1. 判断**公司主体**；
2. 判断**想看四个栏目中的哪几个**（1–4 个）；
3. 通过 LangGraph Orchestrator **只派发被选中的子图**；
4. 报告**只渲染选中栏目**（未选栏目不出现，也不写拒答话术）；
5. 用对话方式回复，并明确告知本次调研范围。

## 2. 已定决策（用户确认）

| 决策 | 结论 | 影响 |
|---|---|---|
| 对话轮次 | **支持多轮** | 会话状态（thread_id → company / last_sections）放 **API 层**，图只负责单轮路由 |
| 意图不明时 | **先追问范围**，不默认全跑 | 路由需要 `clarify(scope)` 分支；追问必须给可点选项 |
| 前端形态 | **对话做首页，原表单保留**为「完整报告」入口 | 新增 ChatPanel，不删 ResearchForm |
| 交互风格 | **多交流**：不确定就问，不猜 | 澄清优先于默认值；范围在报告顶部显式标注 |

## 3. 架构位置

```
用户消息 → route(新节点) → research(orchestrator) → briefing → 回复
                │                 │                      │
                └─ clarify ───────┘                      └─ 只渲染 requested_sections
```

- 路由是**图内节点**，不是 API 层判断——这样可被单测与评测覆盖；
- 会话状态在 API 层，图保持无状态（除 checkpoint）；
- 复用现有 `Send` 派发机制：`dispatch_edge` 已经按 state 里的白名单发 `Send`，不需要改机制，只需给出正确名单。

## 4. 路由规格

### 4.1 输出（结构化）

```json
{
  "company": "Notion",
  "sections": ["financial", "news"],
  "need_clarify": false,
  "clarify_kind": null,
  "question": null,
  "reason": "用户点名融资与新闻"
}
```

`clarify_kind`：`company`（缺主体）/ `scope`（有主体但没范围）/ `followup`（指代不明）。

### 4.2 判定规则

- 栏目映射：公司概况=公司是什么/做什么/成立/总部/规模；行业概况=行业/市场/竞品/份额；财务概况=营收/融资/估值/财报；新闻动态=最近动态/发布/合作/收购。
- 允许多选；`"全部/全面/完整调研"` → 四栏。
- **否定排除**：`"不要新闻"` → 其余三栏。
- 只给公司、没给范围 → `clarify(scope)`（用户决策：不默认全跑）。
- 没给公司 → `clarify(company)`。
- 多轮指代（`"那财务呢"`）→ 由 API 层把上轮 company 注入，路由只需判 sections。

### 4.3 兜底（无 key / fixture / LLM 失败）

- 关键词规则：财务/融资/营收/估值 → financial；竞品/行业/市场 → industry；新闻/动态/发布 → news；公司/介绍/成立 → company。
- 规则判不出范围 → `clarify(scope)`，**不猜全跑**。
- 规则判不出公司 → `clarify(company)`。
- 非法输出（空集、未知栏目名）→ 丢弃非法值后按兜底处理，并留痕 `route` note。

## 5. 运行时契约

### 5.1 `POST /chat`

请求：`{"message": "...", "thread_id": "可选"}`

**追问**：

```json
{"type": "clarify", "thread_id": "t-1", "company": "Notion",
 "clarify_kind": "scope",
 "question": "你想看 Notion 的哪几块？",
 "options": [{"key":"company","label":"公司概况"},{"key":"industry","label":"行业竞争"},
             {"key":"financial","label":"财务融资"},{"key":"news","label":"新闻动态"},
             {"key":"all","label":"全都要"}]}
```

**受理**：

```json
{"type": "accepted", "thread_id": "t-1", "job_id": "...", "company": "Notion",
 "sections": ["financial","news"], "route": {"source":"llm","reason":"..."}}
```

### 5.2 进度

复用 `GET /research/{job_id}/stream`，新增首个事件：

```json
{"type":"route","company":"Notion","sections":["financial","news"]}
```

### 5.3 会话

`thread_id → {company, last_sections, turns[]}`；追问后用户回「财务和新闻」时，用上轮 company 合并再发起。会话存储先走内存，`JOB_STORE=postgres` 时落库。

## 6. 改动清单

| 文件 | 改动 |
|---|---|
| `graph/nodes/router.py`（新） | LLM 结构化路由 + 规则兜底 + 输出校验 |
| `graph/state.py` | 新增 `requested_sections`、`route_meta`、`clarify` |
| `graph/builder.py` | `grounding → route → research → briefing` |
| `graph/orchestrator.py` | `pending_sections` 改读 `requested_sections`；`arbitrate` 只统计选中栏目 |
| `graph/nodes/report.py` | 第 195 行起只遍历 `requested_sections`（不再把「未派发」当「拒答」） |
| `graph/nodes/human_review.py` | 复核预览只列选中栏目 |
| `application.py` | 新增 `POST /chat`、会话表；SSE 增加 `route` 事件 |
| `ui/src/components/ChatPanel.tsx`（新） | 消息列表、范围 chips、补全入口 |
| `ui/src/App.tsx` | 首页切对话，保留「完整报告」入口 |
| `tests/` | 路由单测、子集报告契约、拓扑/轨迹断言更新 |
| `evals/` | 新增 routing accuracy 与 6–8 条子集 case |

## 7. 阶段与验收

| 阶段 | 验收标准 |
|---|---|
| P1 路由节点 | 20 条中文 utterance 单测；LLM 路径注入式、规则路径全 0 调用；非法输出被纠正并留痕 |
| P2 子集派发与报告 | 只选财务+新闻：报告仅两段、References 只含这两段 URL、其余栏目零出现（不是拒答话术） |
| P3 `/chat` + 会话 | 「帮我查 Notion 财务」→ accepted `[financial]`；「帮我查一下」→ clarify(scope)；「那新闻呢」→ 继承 company |
| P4 前端对话 | 一句话出报告；范围 chips 可见；「补全其余栏目」可一键重跑 |
| P5 评测 | 旧 case 默认全选、基线不漂移；新增 routing case 有期望集合比对 |
| P6 live | 2 条真跑：全量 1 条 + 只财务 1 条，量化后者省下的检索次数 |

## 8. 风险

1. **路由少判栏目** → 报告静默变短。缓解：报告顶部标注范围 + 「补全其余栏目」入口。
2. **多轮指代**：图内不做指代消解，交给 API 层注入 company；指代仍不明 → `clarify(followup)`。
3. **评测被动**：新增 `route` 节点会改 `node_trace`，「四段齐全」类断言需区分 requested/降级。
4. **fixture 抖动**：规则兜底必须确定性；LLM 路径只能用注入式测试。
5. **成本**：每轮 +1 次路由 LLM 调用（约 200 tokens）；只选 1 栏反而省检索。

## 9. 不做的事

- 不把整张图改成聊天机器人（state 里塞 messages 语义会与 HITL interrupt 冲突）；
- 不在聊天里做人工复核（保留旧端点的 HITL）；
- 不为了「看起来智能」让 LLM 自由发挥栏目名——只允许四个固定 key。

## 10. 实施记录

### P1 意图路由节点（已完成 2026-11-18）

- `graph/nodes/router.py`：`RouteDecision`（与 LLM 结构化输出共用）+ 规则兜底 + 校验。
- 主图变 6 节点：`grounding → route → research → briefing`；**route 只写 state，不改派发**，
  这样 P1 不会把评测基线一起带偏（gate 仍全 1.0）。
- 新增 state 字段：`user_message` / `requested_sections` / `route_meta` / `clarify`；
  `requested_sections` 与旧 `sections_to_research`（重试白名单）刻意分开。
- 规则覆盖：单选/多选/「不要新闻」排除/「全部」/只给公司→追问范围/指代→追问公司；
  中文公司名覆盖「只看X的财报」「X最近…」，并对「什么/那家/我们」等做停用词拦截。
- 验证：新增 16 个测试（LLM 路径注入，0 真实调用）；**612 passed**；评测 gate PASS。
- 真实 DashScope 抽检 3 条（无检索、仅小模型调用），判定与规则一致；
  抽检发现并修掉「LLM 返回 company=null」的缺口（节点用启发式补公司名，追问话术带主体）。
