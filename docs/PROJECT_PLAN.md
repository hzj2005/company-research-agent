# 项目方案：可溯源的自纠正公司调研 Agent

> 阶段 0 交付物。本文是后续所有编码的唯一设计依据；编码规范见仓库根 `AGENT.md`，运行契约见 `.env.example` 与 `config/*.yaml`。
> 制定日期：2026-11-14

---

## 1. 项目定位与边界

### 1.1 一句话

把 `guy-hartstein/company-research-agent`（Apache-2.0）原有的**线性 DAG 公司调研流水线**，改造成一套**带证据充分性判定与自纠正回路、每条结论可对回原文、可回归评测**的 LangGraph 状态工作流，并用自建评测集量化改造收益。

### 1.2 归因声明（必须贯穿全程）

- 本项目是**基于开源仓库二次开发**，不是独立设计。保留原仓库 `LICENSE`、版权声明、fork 来源与 commit 历史。
- 简历、README、commit message 一律写明「基于 `guy-hartstein/company-research-agent`（Apache-2.0）二次开发」。
- 原版已有功能（四路并行检索、Tavily 相关性筛选、PDF 导出、SSE 进度）不得写成自己的独立设计。

### 1.3 业务落点（决定真不真）

真实需求是成立的：Crunchbase / ZoomInfo / Apollo / Clay / LinkedIn Account IQ 都在做「见客户、面试、看竞品前先摸一遍公司」；Salesforce 2026 State of Sales 调研称 AI agent 预计减少 34% 调研时间。

但**「写一份公司简报」在 2026 年已经是最不值钱的一层**（通用 AI 深研究几分钟即可完成），且行业共识是「AI 调研省时间的前提是每条结论都能对回原文」。

因此本项目的业务落点不是「解决销售调研痛点」，而是：

> **复现一条自动化调研流水线，并解决它最要命的可信度问题：查不到时硬凑、结论无法溯源、改动无法证明没退化。**

这个落点不需要虚构甲方、不需要销售团队、不需要 CRM，用户和评测者都是开发者本人，业务和技术第一次对得上。

### 1.4 明确不做

- 不做真实金融尽调（不接财报 API / Wind，不给出投资建议）
- 不虚构企业客户、上线量级、留存率、准确率数字
- 不引入「业务方审批」这类自己答不上来的角色
- 不做向量库、多模态、微服务拆分等与主线无关的堆料

---

## 2. 现状基线（代码级核查结论）

### 2.1 原版用了什么 / 没用什么

| 维度 | 实际情况 | 代码位置 |
|---|---|---|
| LangGraph | `StateGraph`、`add_node`、`add_edge`、`set_entry_point` / `set_finish_point`、`compile()`、`astream` | `backend/graph.py` L5、L60–104 |
| LangChain | `ChatOpenAI` / `ChatGoogleGenerativeAI` / `BaseChatModel`；LCEL 链 `ChatPromptTemplate \| llm \| StrOutputParser()` | `backend/llm.py` L13–14；`backend/nodes/briefing.py` L113 |
| 部署配置 | `langgraph.json` 支持 LangGraph Server / Studio | `langgraph.json` |
| 依赖 | `langchain==1.3.9`、`langchain-openai==1.2.1`、`langchain-google-genai==3.0.3`、`langchain-community==0.4.1` | `requirements.txt` |
| **完全没有** | `checkpointer`、`interrupt`、`add_conditional_edges`、`with_structured_output`、`BaseRetriever`、`@tool`、`Command`、`Send`、reducer、`add_messages` | 全仓库 grep 确认；`compile()` 无参数 |

**结论**：原版把 LangGraph 当成 DAG 执行器用，用 Python 函数调用 + `asyncio.gather` 也能达到同样效果。这正是「深度浅」的准确含义。

### 2.2 三个必须修的问题

1. **状态契约松**：`graph.py` L60 是 `StateGraph(InputState)`，而真正定义 18 个业务字段的是 `state.py` L14–31 的 `ResearchState`；`application.py` L127 靠 `final_state.update(state)` 手动累积流输出，L141 还留了 `final_state.get('report') or (final_state.get('editor') or {}).get('report')` 双重 fallback。加并行写回和循环前必须先收紧。
2. **不可溯源**：`references.py` L231 只取 top 10 URL 生成末尾 MLA 列表，正文没有任何行内引用标记，无法判断哪句话来自哪篇。
3. **查不到也硬凑**：四个 briefing prompt 都写了 `Never mention "no information found"`（`backend/prompts.py` L10–107），检索为空时模型倾向编造。

### 2.3 原版输出结构（`COMPILE_CONTENT_PROMPT` 写死）

| 栏目 | 子项 |
|---|---|
| Company Overview | 核心产品/服务、领导团队、目标客户、差异化、商业模式 |
| Industry Overview | 市场规模与增速、直接竞品、竞争优势、市场挑战 |
| Financial Overview | 融资轮次/金额/投资方、收入模式 |
| News | 重大公告、合作、获奖与媒体报道 |
| References | 最多 10 条 MLA 引用 |

---

## 3. 目标架构

### 3.1 分层

```
UI / FastAPI（几乎不改）
        ↓
图编排层  graph/            ← 主图、research 子图、条件函数、降级节点
        ↓
能力层    capabilities/     ← Tavily Retriever、LLM 工厂、Pydantic 结构化输出、引用渲染
        ↓
持久化层  persistence/      ← Checkpointer（SQLite / Postgres）、thread_id
        ↓
评测层    evals/            ← golden set、指标脚本、A/B、scorecard、CI
```

### 3.2 主图节点表

| 节点 | 来源 | 输入 → 输出 | 备注 |
|---|---|---|---|
| `grounding` | 原版 | 输入字段 → 初始化 State | 保留 |
| `research_subgraph` | 重构 | 4 个 analyst 并行 → 四类文档 | 由原版 4 条并行边收成子图 |
| `collector` | 原版 | 计数与日志 | 保留 |
| `curator` | 原版 | Tavily 分数过滤 → 候选文档 + 引用池 | 阈值改由配置驱动 |
| **`evidence_check`** | **新增** | 覆盖度/分数/是否硬凑 → 判定结果 | 核心判定节点 |
| **`rewrite_queries`** | **新增** | 不足类目 → 改写后的 query | 回退目标 |
| **`degrade`** | **新增** | 重试超限 → 明确「无公开依据」 | 防幻觉出口 |
| `briefing`（拆成 4 节点） | 重构 | 文档 → 结构化四段简报 | 图并行，去掉节点内 gather |
| **`human_review`** | **新增** | `interrupt()` 复核高风险事实 | 定位为标注/复核入口 |
| `editor` | 原版 | 合并、去重、附引用 → 最终报告 | 引用改为行内 |

### 3.3 条件边与循环

```
curator → evidence_check
evidence_check ── sufficient ──→ briefing
               ── insufficient & retry_count < 2 ──→ rewrite_queries ──→ research_subgraph（回路）
               ── retry_count >= 2 ──→ degrade ──→ briefing（该栏目输出拒答）
briefing → human_review → editor → END
```

- 回退必须用 `Command(goto=...)` 精确指向需要重搜的 analyst，**禁止用无条件边唤醒全部 4 个 analyst**（成本翻 4 倍）。
- `retry_count` 按栏目独立计数，上限读 `config/settings.yaml`。
- 每个条件函数必须可单测：给定 State → 断言返回的分支名。

### 3.4 子图

`research_subgraph` 内部仍是 4 个 analyst 并行；对外只暴露「四类文档」输出。主图因此从 11 个平铺节点收敛为 6～7 个，可白板完整画出。

---

## 4. State 设计（编码前必须定稿）

```python
from typing import Annotated, TypedDict, NotRequired, Required
from operator import add

class InputState(TypedDict, total=False):
    company: Required[str]
    company_url: NotRequired[str]
    hq_location: NotRequired[str]
    industry: NotRequired[str]
    job_id: NotRequired[str]
    thread_id: NotRequired[str]

def merge_docs(left: dict[str, dict], right: dict[str, dict]) -> dict[str, dict]:
    """按 URL 去重合并；回退重搜时保留旧证据，新证据覆盖同 URL。"""
    return {**left, **right}

class ResearchState(InputState):
    messages: Annotated[list, add_messages]
    company_data:   Annotated[dict[str, dict], merge_docs]
    industry_data:  Annotated[dict[str, dict], merge_docs]
    financial_data: Annotated[dict[str, dict], merge_docs]
    news_data:      Annotated[dict[str, dict], merge_docs]
    curated_data:   dict[str, dict]
    evidence_verdict: dict[str, str]        # section -> sufficient | insufficient | degraded
    retry_count:    dict[str, int]          # section -> 已重试轮数
    rewrite_queries: dict[str, list[str]]   # section -> 改写后的 query
    briefings:      dict[str, dict]         # section -> 结构化简报（Pydantic dump）
    references:     Annotated[dict[str, dict], merge_docs]  # url -> {title, score, used_by}
    review_notes:   list[dict]              # HITL 复核留痕，可导出为评测标注
    report:         str
```

**约定**：

- 跨节点写入的字段**必须**在 `ResearchState` 声明；并行写同一字段**必须**配 reducer。
- `messages` 用 `add_messages`；文档字典用按 URL 去重的 `merge_docs`（不能直接用 `operator.add`，因为值是 dict）。
- `retry_count` 是循环终止的唯一依据，禁止用「模型自己说够了」当终止条件。

---

## 5. 数据契约与可溯源

### 5.1 结构化输出

用 `with_structured_output(PydanticModel)` 替换自由文本 bullet，禁止裸 `json.loads`：

```python
class Fact(BaseModel):
    claim: str
    source_url: HttpUrl
    confidence: float = Field(ge=0.0, le=1.0)

class FundingRound(BaseModel):
    round_name: str
    amount: str | None
    announced_on: str | None
    investors: list[str]
    evidence: Fact

class SectionBrief(BaseModel):
    section: Literal["company", "industry", "financial", "news"]
    facts: list[Fact]
    degraded: bool = False
    degrade_reason: str | None = None
```

- 校验失败 → 重试一次 → 仍失败则该栏目降级，记录到 `review_notes`，禁止静默丢字段。
- `source_url` 非空是硬约束；没有来源的 `Fact` 一律丢弃。

### 5.2 行内引用

每条 bullet 渲染为 ``* 结论 [来源标题](url)``，末尾 References 由**同一份 `references` 字典**生成，不再独立挑 top 10。这样「引用可回溯率」才能被脚本自动计算。

### 5.3 降级话术

删除所有 `Never mention "no information found"` 类指令，改为：证据不足或重试超限时，该栏目输出「该类信息未找到公开依据」并置 `degraded=True`。这是本项目最核心的可信度改造。

---

## 6. HITL 设计

- 位置：`briefing` 之后、`editor` 之前，`interrupt()` 暂停，展示融资数字、高管姓名等高风险 `Fact` 及其来源。
- 恢复：`Command(resume={...})` 继续，复核结果写入 `review_notes`。
- **定位**：这是「开发者复核 + 标注入口」，不是业务方审批流。复核记录顺手沉淀为 golden set 的标注来源。
- 依赖：必须先接入 checkpointer，否则无法恢复；`thread_id` 按配置模板生成。

---

## 7. 评测台设计

### 7.1 golden set

`evals/golden.jsonl`，30～50 家公司 × 每家 5 条可核验事实：

```json
{"company": "Notion", "industry": "Productivity Software", "facts": [
  {"field": "ceo", "expected": "...", "source_hint": "official about page"},
  {"field": "funding_round", "expected": "...", "source_hint": "press release"},
  {"field": "founded_year", "expected": "...", "source_hint": "..."},
  {"field": "competitor", "expected": "...", "source_hint": "..."},
  {"field": "recent_launch", "expected": "...", "source_hint": "..."}
]}
```

其中故意混入若干**查不到公开依据**的公司，用于测拒答率。

### 7.2 指标

| 指标 | 定义 |
|---|---|
| 事实正确率 | 命中 expected 的字段数 / 总字段数 |
| **引用可回溯率** | 带 `source_url` 且该 URL 内容确实支持 claim 的结论占比（核心指标） |
| 无依据拒答率 | 应拒答样本中正确输出「无公开依据」的比例 |
| 幻觉率 | 无来源或与来源矛盾的结论占比 |
| 自纠正成功率 | 首轮证据不足、经回退后转为 sufficient 的比例 |
| 平均重试轮数 / p95 延迟 / 单次成本 | 工程指标，用于讲成本取舍 |

### 7.3 A/B 与 CI

四组开关（对应 `config/eval.yaml`）：`self_correction` 关、`max_results` 减半、`structured_output` 关、`human_review` 关。每次改动跑全量，scorecard 写入 `evals/scorecard.json` 并提交；CI 比对上一版，任一核心指标回退超过容差即失败，并打印退化用例 id。

---

## 8. 配置与环境：fixture / live 双模式

用户当前**没有模型与检索 API key**，因此配置必须先支持无 key 跑通。

| 模式 | 触发 | 检索 | 模型 | 用途 |
|---|---|---|---|---|
| `fixture`（默认） | `APP_MODE=fixture` | 读 `evals/fixtures/tavily_responses.json` 固定结果 | 确定性 stub，返回预设结构化输出 | 跑通图、循环、reducer、interrupt、评测脚本；结果完全可复现 |
| `live` | `APP_MODE=live` | 真实 Tavily | 真实 OpenRouter / OpenAI | 真实实测、产出简历数字 |

**切换只允许改 `.env`，不允许改代码**。fixture 必须覆盖三类样本：资料充足、资料稀疏（触发回退）、完全查无（触发降级拒答），否则循环逻辑无法被测试。

配置文件职责：

- `.env.example`：全部密钥与运行模式占位，禁止提交真实 `.env`
- `config/settings.yaml`：图参数（重试上限、阈值）、检索参数、模型角色、feature flags
- `config/eval.yaml`：评测集路径、指标阈值、A/B 覆盖项、CI 容差

环境变量优先级高于 yaml；yaml 中用 `${VAR:-default}` 占位，由 `config/loader.py` 统一解析。

> **验证状态（2026-11-14，S1 已补做）**：独立 venv 装好 PyYAML 6.0.3 后，两份 YAML 已用真实 `yaml.safe_load` 全量解析通过，结构级自检的欠账已解除，详见 `docs/BASELINE.md` 第 1 节。**注意**：本轮只验证了 YAML 语法，`${VAR:-default}` 占位符展开仍由 S2 的 `config/loader.py` 实现并纳入 CI 校验。

---

## 9. 目标目录结构

```
company-research-agent/
├── AGENT.md                    # 编程规范（阶段 0B）
├── docs/PROJECT_PLAN.md        # 本文
├── .env.example                # 阶段 0C
├── config/
│   ├── settings.yaml
│   ├── eval.yaml
│   └── loader.py               # 后续实现
├── backend/                    # 基于原仓库二次开发，保留原 LICENSE
├── graph/                      # 主图、子图、条件函数、降级节点
├── capabilities/               # Retriever、LLM 工厂、Pydantic schema、引用渲染
├── persistence/                # checkpointer 与 thread_id
├── evals/
│   ├── golden.jsonl
│   ├── fixtures/tavily_responses.json
│   ├── run_eval.py
│   └── scorecard.json
├── tests/                      # 每个节点/条件函数一个用例文件
└── .github/workflows/eval.yml
```

---

## 10. 里程碑与验收（对应任务清单）

| 阶段 | 任务 | 验收 |
|---|---|---|
| 0A / 0B / 0C | #10 #11 #12 | 方案、规范、配置三份产出可直接指导编码，双模式可切换 |
| M1 | #1 | 真实跑通原版，产出 baseline 报告与耗时/成本记录 |
| M2 | #2–#6 | 重启可恢复、回路 2 轮内收敛、每条结论能对回 URL、中断恢复 State 一致 |
| M3 | #7 #8 | 一条命令出 scorecard，能定位退化用例，所有数字可复现 |
| M4 | #9 | 3–4 条简历描述，每条能指到具体文件与 commit |

工作量估计：1–2 周（每晚 2–3 小时）。UI 与 FastAPI 层基本不动。

---

## 11. 风险与取舍

1. **并行写覆盖**：4 个 analyst 各写独立字段没问题，但回退重搜合并新文档时，`merge_docs` 必须按 URL 去重，否则第二轮冲掉第一轮证据。
2. **回退放大成本**：必须用 `Command(goto=...)` 精确指向单个 analyst，禁止无条件边唤醒全部节点。
3. **interrupt 依赖 checkpointer**：两者必须一起做（`compile(checkpointer=...)`），并验证 `thread_id` 隔离。
4. **成本与延迟翻倍**：加 2 轮重试 + 判定节点后 token/延迟约翻倍 → 按「信息好不好查」路由，简单公司不走完整回路。这是面试里最值钱的工程取舍。
5. **业务坑比技术坑大**：人工确认会被问「谁来确认」，所以绝不包装成审批流。
6. **归因风险**：这是有 2317 star 的公开仓库，简历写「独立开发 / 生产上线」一搜就穿。

---

## 12. 简历落点（数字跑完再填，禁止预填）

- 基于 `guy-hartstein/company-research-agent`（Apache-2.0）二次开发，将原线性 DAG 重构为带证据充分性判定与上限回退的 LangGraph 状态图，重试达限自动降级为「无公开依据」拒答，消除原实现查不到仍硬凑的幻觉
- 以 `ResearchState` + reducer 统一并行节点写回，Checkpointer 按 `thread_id` 持久化调研轨迹，支持断点续跑与失败回放；成稿前 `interrupt` 复核高风险事实并 `Command(resume=...)` 恢复
- 将 Tavily 封装为 LangChain Retriever，用 `with_structured_output` + 字段级置信度替换自由文本并为每条结论附行内来源；自建 X 家公司 / Y 条可核验事实的 golden set 接入 CI 回归，引用可回溯率由 X 提至 Y、幻觉率由 X 降至 Y

---

## 附录：原仓库关键代码位置索引

| 事项 | 位置 |
|---|---|
| 建图（11 节点、线性边、无参 compile） | `backend/graph.py` L60–104 |
| `InputState` / `ResearchState` 定义 | `backend/classes/state.py` L7–31 |
| 请求模型 | `application.py` L54–61 |
| 流输出累积与取报告 fallback | `application.py` L127、L141 |
| 相关性阈值 0.4 | `backend/nodes/curator.py` L15、L37 |
| 引用池 top 10 | `backend/utils/references.py` L231 |
| Tavily 抓全文 | `backend/nodes/enricher.py` L28 |
| 搜索参数（2 query × 3 results） | `backend/nodes/researchers/base.py` L155–166、`backend/prompts.py` `QUERY_FORMAT_GUIDELINES` |
| 并行简报（Python gather） | `backend/nodes/briefing.py` L154–200 |
| 四段简报模板 / 报告结构 | `backend/prompts.py` L10–107、L117、L149 |
| LCEL 链 | `backend/nodes/briefing.py` L113 |
| 内置 24 家示例公司 | `ui/src/components/ExamplePopup.tsx` L4–69 |
