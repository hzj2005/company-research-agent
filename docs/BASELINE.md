# S1 原版基线（实测记录）

> 采集脚本：`baseline/inspect_upstream.py` | 机器可读结果：`baseline/upstream_graph.json`
> 采集时间：2026-11-14 13:10 | 上游 commit：`23fe92d48ea05750e6fd7cffdb78799cea5278d8`
> 复现：`uv run python baseline/inspect_upstream.py`

---

## 0. 先说清楚「跑通」到什么程度

| 项 | 状态 | 证据 |
|---|---|---|
| 原仓库落地工作区、保留 LICENSE 与上游 commit | ✅ | `LICENSE`（SHA256 `92799ec7…`）、`.git` remote `upstream` |
| 独立 venv 装齐依赖 | ✅ | `requirements.lock.txt`（99 个包） |
| 两份 YAML 全量解析校验 | ✅ | `yaml.safe_load` 通过，见第 1 节 |
| **真实 import + 构造 + `compile()` 原版 StateGraph** | ✅ | 第 2 节，从图对象导出结构 |
| **真实执行 3 个不联网节点** | ✅ | 第 4 节，grounding / collector / curator |
| 完整 `/research` 调研跑出真实报告 | ❌ **未做** | 缺模型 / Tavily key，见第 6 节 |
| 原版耗时、token、成本基线 | ❌ **未做** | 同上；**不编造数字** |

**本脚本不发起任何外部网络请求**。占位 key 只是为了让上游构造函数通过非空校验（`backend/nodes/researchers/base.py` L20–25、`backend/llm.py` L74–79），不会真的调 Tavily 或模型。因此它证明的是「原版图能被真实构造和编译」，**不能**冒充「完整调研已跑通」。

---

## 1. 环境与依赖（实测，非假设）

| 项 | 值 |
|---|---|
| 解释器 | Python 3.11.9（`D:\Python\Python311`），独立 `.venv` |
| pip 源 | `https://pypi.org/simple`（清华镜像返回 `from versions: none`，不可用） |
| langchain / langchain-core | 1.3.9 / 1.8.0 |
| **langgraph / langgraph-checkpoint** | **1.2.22 / 4.3.2**（原 `requirements.txt` 未显式声明，是传递依赖；本项目已显式安装） |
| pydantic / PyYAML / pytest | 2.14.3 / 6.0.3 / 9.2.0 |
| tavily-python / fastapi | 0.7.24 / 0.121.2 |

**阶段 0 欠账已补**：`config/settings.yaml` 与 `config/eval.yaml` 用真实 `yaml.safe_load` 全量解析通过。
- settings 顶层键：`app / graph / retrieval / models / features / report`；`graph.max_retry = 2`；`app.mode = ${APP_MODE:-fixture}`
- eval 顶层键：`dataset / fixture / metrics / thresholds / ab_tests / ci`
- 结论：`docs/PROJECT_PLAN.md` 第 8 节的「未验证可用」标记已解除；`${VAR:-default}` 的解析将在 S2 由 `config/loader.py` 实现（本轮只验证语法，未验证占位符展开）。

---

## 2. 原版图结构（从编译后的图对象导出，不是 grep 源码）

`Graph(...).compile()` 返回 `CompiledStateGraph`，`get_graph()` 导出：

- **节点 12 个**：`__start__`、`__end__` + 10 个业务节点
  `grounding` → 4 路并行（`financial_analyst` / `news_scanner` / `industry_analyst` / `company_analyst`）→ `collector` → `curator` → `enricher` → `briefing` → `editor`
- **边 14 条，条件边 0 条**
- 入口 `__start__ → grounding`，终点 `editor → __end__`
- `compile()` 无参数 → **无 checkpointer**

> 这与 `docs/PROJECT_PLAN.md` 第 2 节的静态核查一致，且现在是动态证据：`backend/graph.py` L60–104 建图的 11 个节点（含 START/END 后为 12）确实全程 `add_edge`，一次分叉判断都没有。

---

## 3. 本轮发现的 3 个原版真实缺陷（S2 要修）

1. **状态 schema 与依赖版本不兼容（新发现）**
   `backend/classes/state.py` L1–2 用 `from typing import TypedDict`。在 Python 3.11 + pydantic 2.14.3 下，`compiled.get_input_schema().model_json_schema()` 直接抛：

   ```
   PydanticUserError: Please use `typing_extensions.TypedDict` instead of
   `typing.TypedDict` on Python < 3.12.
   ```

   图本身能编译，但**状态 schema 无法内省/校验**。S2 重写 `ResearchState` 时必须改用 `typing_extensions.TypedDict`，并补一条 schema 内省的 pytest 用例。

2. **State 契约松且节点就地改 State**
   `graph.py` L60 是 `StateGraph(InputState)`（5 个字段），而 18 个业务字段定义在 `ResearchState`；`curator.py` L147、L155–157 直接 `state[...] = ...` 修改传入对象，`collector.py` L30 直接 append `messages`。本轮执行也证实 `curator_added_keys` 是原地新增的。按 `AGENT.md` 第 6 条，S2 必须收紧为纯函数 + reducer。

3. **无循环 / 无降级 / 无持久化**
   条件边 0 条、无 `checkpointer`、无 `interrupt`；四个 briefing prompt 还写了 `Never mention "no information found"`（`prompts.py` L10–107），检索为空时倾向硬凑。这是 S3 / S5 的核心改造点。

---

## 4. 纯节点真实执行结果

构造一份不联网的 State（`Notion`，含 4 条带分数的 fixture 文档），依次 `await` 三个节点：

| 观察项 | 实测结果 |
|---|---|
| `GroundingNode.run()` 输出字段 | `company / company_url / hq_location / industry / job_id / messages / site_scrape`（`company="Notion"`） |
| `Collector.run()` 新增字段 | 无（只往 `messages` 追加一条汇总消息，原地修改） |
| `Curator.run()` 新增字段 | `curated_financial_data / curated_news_data / references / reference_titles / reference_info` |
| 分数过滤效果 | financial 输入 2 篇（0.91 / 0.12）→ 保留 **1** 篇；news 1 篇（0.77）→ 保留 **1** 篇；company 1 篇（0.05）→ 保留 **0** 篇 |
| 引用数 | `references_count = 2` |

阈值 0.4 来自 `curator.py` L15 硬编码；`company_data` 那篇因分数 0.05 且 `source != 'company_website'` 被丢弃（`curator.py` L34–37）。这正好是 S2 要把阈值改为配置驱动、S3 要做「证据不足判定」的现场证据。

---

## 5. 原版输出结构（静态，来自 `backend/prompts.py`）

`COMPILE_CONTENT_PROMPT`（L117）与四个 briefing prompt（L10–107）写死五段：

| 栏目 | 子项 |
|---|---|
| Company Overview | 核心产品/服务、领导团队、目标客户、差异化、商业模式 |
| Industry Overview | 市场规模与增速、直接竞品、竞争优势、行业挑战 |
| Financial Overview | 融资轮次/金额/投资方、收入模式 |
| News | 重大公告、合作、获奖与媒体报道 |
| References | 末尾最多 10 条 MLA 引用（`references.py` L231），**正文无行内引用** |

保持这个结构不变，是为了让 S7 的前后对比有同一把尺子。

---

## 6. 未完成项与阻塞条件（不伪装完成）

- **完整 `/research` 真实调研**：`Graph.run()`（`graph.py` L96–104）会真的调 Tavily `search` / `extract` 和 LLM，当前没有 `OPENROUTER_API_KEY` / `TAVILY_API_KEY`，强行跑只会失败或产生不可信输出。
- **耗时 / token / 单次成本基线**：同上，没有真实调用就没有任何可信数字。
- 这两项按 `docs/ACTION_PLAN.md` 挂到 **S8（真实实测）**；S2–S7 先在 `fixture` 模式下把图、循环、reducer、interrupt、评测台跑通，等 key 到位只改 `.env` 的 `APP_MODE=live` 即可补齐。
- 在此之前，简历与文档里**不出现任何准确率、耗时、成本数字**。

---

## 7. S2 验证记录（2026-11-14，状态契约与真实持久化）

新增模块：`config/loader.py`、`graph/state.py`、`persistence/checkpointer.py`、`tests/`（3 个测试文件 + conftest）、`pytest.ini`。
运行：`uv run python -m pytest -q` → **10 passed**（S2 当时为 10 个；S2 后复查补测增至 16 个，见第 8 节）。

| 验收点 | 真实测试结果 |
|---|---|
| 配置 `${VAR:-default}` 展开 + Pydantic 严格校验 | `load_settings()` 解析出 max_retry=2、4 个 section、阈值 0.4；环境变量覆盖生效 |
| `typing.TypedDict` 缺陷已修 | `StateGraph(ResearchState).compile().get_input_schema()` 不再抛 `PydanticUserError`；`get_output_schema()` 返回 19 个字段 |
| 并行 reducer 不覆盖 | 两节点并行写 `company_data`，最终同时保留 `u1/u2`；`add_messages` 累加两条消息 |
| checkpoint 真落盘 | db 文件存在且非空（非 InMemorySaver） |
| **重启恢复** | 关闭 session 后重新打开同一 db，`aget_state()` 读回 report / company_data / messages，与重启前一致 |
| **thread_id 隔离** | 另一 thread 的 `aget_state()` 读不到 Notion 的状态 |
| 同 thread 续跑 | 两次 `ainvoke` 后 messages 累加为 `["wrote","wrote"]`，未覆盖 |

**实测踩到并修掉的两个 API 事实**（已写进 `AGENT.md`）：
1. 同步 `SqliteSaver.aget_tuple()` 抛 `NotImplementedError`，async 图必须改用 `AsyncSqliteSaver` + `ainvoke` / `aget_state`；
2. LangGraph 1.2 的 `get_input_schema()` 只列外部输入 channel（空），完整字段要用 `get_output_schema()`。

**S2 仍未做的**：尚未把原版 11 节点图切到新 `ResearchState`（S3–S4 会重建图），因此本阶段的验证用的是最小验证图，不是完整业务图。这一点在 S4 完成后必须补一条端到端用例。
→ **已于同日第二次复查中提前补上，不必等 S4**：见第 10 节，用例改用 S3 真实 7 节点业务图。

---

## 8. S2 后复查补账（2026-11-14）

用户要求「先检查上一步是否干好，再进下一阶段」。逐条对账后确认核心功能无误（配置展开、schema 内省、并行 reducer、checkpoint 落盘/重启恢复/thread 隔离均真跑通过），但补了 5 项：

1. **改 uv 环境**：原 `.venv` 由 `python -m venv` 建；现由 `uv venv --python 3.11 --clear` 重建，`.venv/pyvenv.cfg` 含 `uv = 0.8.15`。新增 `pyproject.toml`（显式声明 langgraph / sqlite saver / pytest / pyyaml，并固定官方 PyPI 源）、`.python-version`、`uv.lock`。`uv sync --frozen` 幂等，`uv pip check` 报 103 包全部兼容。
2. **修 `langgraph.json` 的隐藏失效**：其 `dependencies: ["."]` 需要项目可安装，此前无 pyproject；`uv sync` 现已成功 build 本项目。
3. **补 fixture 样本**：`evals/fixtures/tavily_responses.json` 三种 case（sufficient / sparse / empty），并声明为合成数据，禁止当真实指标来源；`tests/test_fixtures.py` 锁住形状与阈值（阈值从 `get_settings()` 读）。
4. **补 reducer 缺口**：`graph/state.py` 新增 `merge_mapping` / `append_unique` / `append_notes`，给所有会被回退重复写入的 dict/list 字段配 reducer；新增 `degraded` / `degraded_sections`。`tests/test_state.py` 新增两轮写回测试，断言其他 section 不被覆盖。
5. **文档同步**：`AGENT.md` 第 3、12、13 节与本文命令全部改为 `uv run`，补「禁止直接 pip install」「禁止无 reducer 重复写」两条红线。

复查后 `uv run python -m pytest -q` → **16 passed**。`requirements.lock.txt` 保留为 S1 历史快照，依赖以 `pyproject.toml` + `uv.lock` 为准。

---

## 9. S3 验证记录（2026-11-14，自纠正回路）

图结构（编译后对象）：7 节点 `grounding / research / curate / evidence_check / rewrite_query / degrade / briefing`，`evidence_check` 挂 3 条条件边（`pass / retry / degrade`），`rewrite_query → research` 构成回路。相对上游「12 节点 / 14 边 / **0 条件边**」是结构性变化。

| 验收项 | 真实结果 |
|---|---|
| sufficient 一轮通过 | research 1 次、retry_count 空、8 篇合格文档、8 条引用 |
| sparse 触发回退并收敛 | research 2 次、company retry=1、回退只重搜 `["company"]`、补足后 sufficient |
| empty 上限收敛并拒答 | research 3 次（max_retry 2 + 首轮）、company retry=2、degraded=true、报告输出「该类信息未找到公开依据」 |
| 不编造 | 低分无关 URL 在报告中出现 0 次；其他栏目内容仍保留 |
| 引用同源 | 正文行内 `[n]` 与末尾 References 同一份 `references` 字典 |
| 开关 A/B | `self_correction=false` → 不回退，直接 degrade |

复现命令：`uv run python -m graph.run --case empty --show-report --trace`；测试 `uv run python -m pytest -q` → 23 passed。

---

## 10. 第二次复查补账（2026-11-14 14:35，S0–S3 全量对账）

用户要求「先检查前两阶段完成情况、有漏的补上」。范围确认为 S0–S3 全部；检查全部真实执行（pytest、三档 CLI、`uv sync --frozen`、`uv pip check`、基线脚本复现），不是静态看代码。

| 项 | 补账前 | 补账后 |
|---|---|---|
| 测试 | 23 passed | **33 passed** |
| A/B 开关 | 只能在测试里 `model_copy` 改对象，命令行关不掉 | `FEATURES_SELF_CORRECTION=false` → research 1 次、degraded=true |
| 引用完整性（造 12 篇合格文档） | 15 条正文里 4 条事实无 `[n]` | 10 条事实全部带 `[n]`，2 条被显式截断并记入 `review_notes` |
| 真图 checkpoint | 只有 1 节点最小验证图 | 7 节点业务图重启恢复 5 个 State 字段 |
| README 归因 | 无，仍是上游原文 | 顶部加二次开发声明与当前真实状态 |

三档 CLI 回归：`report_chars` 822 / 829 / 561，与第 9 节完全一致，无行为回归；`uv sync --frozen` 幂等、`uv pip check` 103 包兼容。

**仍如实存在的边界**：`evidence_check` 只做覆盖度判定（数篇数），不做「来源是否支持结论」的内容级判断。empty 报告里其余三栏会输出「该领域缺少公开规模数据」这类无实质信息的合成句并带 `[n]`。形式上的「正文引用与 References 同源」已达成，但 `config/eval.yaml` 定义的 `citation_traceability`（来源确实支持 claim）需要 S7 的 judge / golden set 才能真正度量，**本阶段不假称已实现**。另外 `langgraph_entry.py` 与 `application.py` 仍指向原版图，按用户拍板等 S5 接真实模型后一次切换。
