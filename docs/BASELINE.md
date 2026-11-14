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

---

## 11. S4 验证记录（2026-11-14，并行子图与精确派发）

新增 `graph/subgraphs/state.py`、`graph/subgraphs/research.py`、`tests/test_s4_subgraph.py`。主图节点名 `research` 保持不变，值换成编译后的子图；子图 `dispatch` 挂真实条件边，用 `Send` 按 `sections_to_research` 白名单派发到 `analyst`。

| 验收点 | 真实结果 |
|---|---|
| 前置 API 探针（uv + AsyncSqliteSaver 临时库） | 编译子图可作主图节点；Send 并行写回经 reducer 合并不覆盖；主图 `astream` 节点名仍是 `research` |
| 首轮并行 | Notion 4 条 analyst 留痕（4 个栏目），四类 `*_data` 全有文档且互不覆盖 |
| 精确回退 | Linear 首轮 4 个 Send、回退轮 **1 个 Send**（仅 company）；empty 两轮回退均只 company |
| 有上限循环 | empty 3 次 research，`degraded=true`，其余栏目正常输出 |
| 三偏差 | `any→all`（部分栏目达上限仍继续重试）；删除名不副实的 `degrade.enabled`；`curated_data`/`references` 改 `replace_mapping`，**仅当同一 URL 的新版本被判低分/无 URL 时**旧引用才被移除 |
| 回归 | `uv run python -m pytest -q` → **43 passed**；三档 `report_chars` 822/829/561、research 1/2/3、引用数 8/9/6，与第 9 节完全一致 |

**实测踩到并修掉的坑**：编译子图直接当主图节点时，若把主图已有的 `review_notes` 传进子图、又由子图输出带回，`append_notes` reducer 会把旧记录重复累加（sparse 首轮 4 条变 8 条）。修法：`StateGraph(..., input_schema=..., output_schema=...)` 隔离子图输入/输出，且 `Send` 只带编排参数、不带累积字段。两个 API 事实已写进 `AGENT.md`：`Send` 从 `langgraph.types` 导入；`StateGraph` 用 `input_schema`/`output_schema`（`input`/`output` 已弃用）。

### 11.1 S4 复查补测（2026-11-14 15:40）

| 复查点 | 真实结果 |
|---|---|
| 编译后图结构 | 主图 `__start__/__end__` + 7 业务节点；子图 `dispatch` + `analyst`，`dispatch` 挂真实条件边 |
| 并行耗时硬证据 | 带 0.15s 延迟的工具：4 路 Send **0.181s**，串行理论 **0.600s**；4 分支全执行、四类 `*_data` 互不覆盖。已固化为 `test_send_branches_overlap_in_time`（时间窗重叠断言，不依赖绝对耗时，避免 CI 抖动） |
| 子图嵌套 checkpoint | 重开 `CheckpointSession` 后 report / references / evidence_verdict / retry_count / review_notes / degraded 六项全部恢复 |
| 栏目级轮次 | 原实现 `max(retry_count.values())` 在 `company=2, industry=1` 时让 analyst 错取 `round_no=2`；已改 `retry_count.get(section, 0)`。**反向验证**：换回旧写法时新增用例报 `captured=[('industry', 2)] != [('industry', 1)]` 失败 |
| 旧引用边界 | `*_data` 按 URL 累积，「URL 不再返回」的旧引用**移除不掉**：实测第 1 轮 old URL、第 2 轮仅新增 new URL，最终 references 仍含 old。已写 `test_url_that_stops_being_returned_is_retained_as_known_limitation` 如实记录；需按栏目维护「本轮有效 URL 集合」才能解决（S5/S7）。`replace_mapping` 只在「同 URL 新版本被判低分」时移除旧引用，已由真实链路用例覆盖 |
| 复查后回归 | `46 passed`；三档 `report_chars` 822/829/561、research 1/2/3、引用 8/9/6 零变化 |

**S4 如实边界**：仍是 fixture 模板简报，不接真实 LLM/Tavily；对外入口仍指原版图（S5 再切）；内容级 `citation_traceability` 仍归 S7。主图本来就是 7 节点，不谎称「从 11 节点收敛到 6～7」。【S4 历史快照：S5-B 起两个入口已切到新图，见第 13 节】

---

## 12. S5.1 验证记录（2026-11-14，结构化输出契约层）

新增 `graph/contracts.py`（`Fact` / `SectionBrief` / `ResearchBrief`，`extra="forbid"`）、`capabilities/llm.py`（配置驱动模型工厂）、`capabilities/structured.py`（LCEL 抽取链 + 校验重试 + URL 级回溯）、`tests/test_s5_contracts.py`（9 个用例）；`config/loader.py` 增加凭据解析（凭据不进 `Settings`，用 `SecretStr`）。

| 验证点 | 真实结果 |
|---|---|
| 无 key 跑 `with_structured_output` | `httpx.MockTransport` 注入 `http_async_client`，`prompt \| with_structured_output(SectionBrief, method="function_calling")` 真发 1 次请求并返回 Pydantic 实例 |
| 校验失败不静默 | 缺 `source_url` → `ValidationError`；重试耗尽 → `degraded=True` + `facts=[]` + 逐次 `review_notes` |
| 重试成功路径 | 第一次非法、第二次合法 → 成功，留痕 `["validation_failed", "ok"]` |
| URL 级回溯 | 文档外 URL 的 Fact 被剔除并写 `dropped_uncited_facts`，整栏降级 |
| 配置驱动 | 改 `models.roles.briefing` 后请求体 `model` 随之改变；温度来自 `settings.models` |
| 完全离网保证 | mock 客户端 `base_url=http://127.0.0.1:1/v1`（不可达），注入一旦失效立即连接失败，不会静默走外网 |
| 回归 | `55 passed`；三档 822/829/561、A/B 开关、`uv pip check` 103 包全部无变化 |

**API 事实（前置探针实测）**：`convert_to_openai_tool(SectionBrief)` 可生成 tool spec；`ValidationError` 与 `OutputParserException` 都是 `ValueError` 子类；`GenericFakeChatModel.with_structured_output` 抛 `NotImplementedError`，因此无 key 测试只能走 mock HTTP；`BaseRetriever` 最小子类 `ainvoke` 可用；新图 `astream(stream_mode="updates")` 产出 `{节点名: {字段: 值}}` 共 5 个事件，可直接喂 `application.py` 的 `current_step`；顶层无 checkpointer 的 `build_graph(...).compile()` 有 9 节点可用；`AsyncSqliteSaver.from_conn_string` 返回 async context manager，不能在模块顶层直接当 saver 用。

**S5.1 如实边界**：以上只验证 LangChain 调用链与数据契约，**未调用任何真实模型 / Tavily**，不产出准确率、延迟、成本数字；live 实测仍阻塞在 key（S8）。`Fact.source_url` 只做到 URL 级回溯，内容级 `citation_traceability` 仍归 S7。

---

## 13. S5-B 验证记录（2026-11-14，8.2–8.5；0 次真实 Tavily / 模型调用）

用户明确约束：`TAVILY_API_KEY` 已设在 Windows 用户级变量，谨慎使用、非必要不调用。**实测**：用户级变量存在（长度 54，未读取明文），当前进程未继承；`OPENROUTER/OPENAI/GEMINI` 三组模型 key 均未设置。因此本阶段把「0 次真实调用」做成可验证的代码事实，而不是约定。

| 验证点 | 真实结果 |
|---|---|
| 三重 opt-in | 默认 `fixture / enabled=false / max_calls=0`；缺任一抛 `LiveRetrievalDisabled`，缺 key 抛 `MissingTavilyCredentials`，**不回退 fixture** |
| 硬预算 + 缓存 | 预算 1 时第 2 次不同 query 抛 `TavilyBudgetExceeded`，fake client 只收到 1 次；缓存命中不扣额度也不凭空增加额度；dry-run 0 次 client 调用 |
| **零外部连接硬证据** | `tests/test_s5_offline.py` 守卫 `socket.connect`（只放行本地回环，Windows asyncio self-pipe 需要），完整跑一次图仍产出 822 字符报告，被拦截的外部连接 = **0**；Studio 入口 reload 时把 `AsyncTavilyClient` 换成抛错哨兵仍通过 |
| 结构化输出真跑 | on 走 `prompt \| with_structured_output(SectionBrief)`，三档留痕 4/4/3 条；off 与 S4 报告**逐字一致**；12 篇文档截断时 10 条结论全带 `[n]`；编造 URL 被剔除并整栏拒答 |
| 入口切换 | Studio 顶层图 7 业务节点、`checkpointer=None`（Server 注入）；`process_research` 用 `CheckpointSession` + `astream(updates)`；**真发 POST `/research`** 完成且报告 822 字符，请求体 key 未被消费或外泄 |
| 回归 | `85 passed`；三档 822/829/561、research 1/2/3、引用 8/9/6 与 S4 一致；两个 A/B 开关生效；`uv pip check` 103 包兼容 |

**本阶段实测踩到并修掉的两个真问题**：① OpenAI 请求体里 human 消息的 role 是 `user` 而非 `human`，mock handler 取错消息 → payload 为空、四栏静默误判降级；改为兼容 `user`/`human` 与多模态 part list，并补回归用例。② `make_briefing_node` 初版用模块级全局 `_index` 传引用编号，并发会串号；改显式传参。另给注入 client 的 `ChatOpenAI` 加 `http_socket_options=()` 消掉 SDK 代理告警。

**S5-B 如实边界**：`AsyncTavilyClient.search()` 的真实行为**未实测**（0 次真实请求）；fixture 结构化输出是确定性 stub，**不代表模型能力**；`/research` 现在只消费 `company`，`company_url/industry/hq_location/model/请求体 key` 均不消费；内容级 `citation_traceability` 仍归 S7；真实准确率/延迟/成本与 S8 实测仍阻塞在「用户明确放行额度」+ 模型 key。

### 13.1 S5-B 复查补账实测（0 次真实调用）

| 复查项 | 真实结果 |
|---|---|
| client 泄漏（修复前） | 连续 5 次 `run_research` → 创建 5 个 `httpx.AsyncClient`、**未关闭 5 个**；`aclose()` 仅测试调用过 |
| client 泄漏（修复后） | `briefing_backend_scope()` 的 `finally` 关闭；同样 5 次运行 → **未关闭 0 个**；`tests/test_s5_lifecycle.py` 另覆盖异常路径与 FastAPI 后台任务路径 |
| confidence 契约 | 修复前 `score=0.41` → `confidence=0.9` 且 prompt 无 score；修复后 → `[0.41, 0.93]` 精确回显，非数值/越界分别夹到 0.0 / 1.0 |
| `/research` 离网硬证据 | 真发 POST + `socket.connect` 守卫（只放行回环）→ `completed`、822 字符、**被拦截外部连接 0 次**，已固化为 `test_s5_offline.py` 第二条用例 |
| 反向验证 | 临时换回旧写法，3 条 lifecycle 用例全部失败；还原后全量通过 |
| 静态排雷 | `AsyncTavilyClient.search` 真实签名含 `query/max_results/search_depth/topic`，`topic` 允许 `general/news/finance`、`search_depth` 允许 `advanced`（**未发起调用**） |
| 回归 | `89 passed`；三档 822/829/561、两个 A/B 开关、`uv pip check` 103 包兼容 |

**新增边界说明**：上游 `GET /models` 会向 OpenRouter 发请求、不受本项目护栏约束（用户拍板只补文档不动上游端点）；`APP_MODE=live` 无模型 key 会在 `build_graph()` 构造期抛 `MissingLLMCredentials`，只跑检索需 `FEATURES_STRUCTURED_OUTPUT=false`；`TAVILY_MAX_CALLS` 是 per-run 预算。

---

## 14. S6 HITL 验证记录（2026-11-14，0 次真实 Tavily / 模型调用）

用户拍板形态：**图内 `interrupt()` + CLI 两步式 resume**，不动上游 SSE、不加 API resume 端点。

**前置探针（真跑）**：`interrupt` / `Command` 均在 `langgraph.types`；首轮 `astream(updates)` 产出 `__interrupt__`，`aget_state().next == ('review',)`；**关闭 `CheckpointSession`、重开指向同一 SQLite 后**用 `Command(resume=...)` 续跑成功，恢复后 `next == ()`。另发现 `test_s4_subgraph.py:97` 精确断言主图 7 节点 → 默认配置不能新增节点。

| 验证点 | 真实结果 |
|---|---|
| 默认零回归 | `FEATURES_HUMAN_REVIEW=false` → 7 节点、无中断；三档 822/829/561 与 S5 逐字一致 |
| 开关打开 | 8 节点（多 `human_review`）；`auto_approve=true` 写 `auto_approved` 不中断；`false` 真暂停 |
| **跨进程恢复** | 两个独立 CLI 进程：第一步打印 payload / thread_id；第二步 `node_trace=["human_review","briefing"]`，前半段从磁盘恢复未重跑，报告 829 字符 |
| 人工决定生效 | `--decision reject-sections --reject-sections news` → 仅 News 段拒答、该栏目引用移除；`--decision reject` → 四栏全拒答、References 空、无「（合成）」残留 |
| fail-safe | 非法 resume 值整份拒答；未知栏目被白名单过滤且去重 |
| 零外部连接 | 复核 + 恢复全程 `socket.connect` 守卫（只放行回环），被拦截外部连接 = **0** |
| 回归 | `97 passed`；两个 A/B 开关生效；`uv pip check` 103 包兼容 |

**S6 如实边界**：只有 CLI，没有前端 / API 复核端点；payload 与 decision 都是 JSON，属**可验证的图编排能力**而非产品化 HITL；`auto_approve_review=true` 是无人值守默认值，避免 `/research` 永久卡在中断。【S6 历史快照】S7 评测台已完成（见第 15 节），S8 真实实测（需模型 key + 用户放行额度）、S9 简历仍未开工。

---

## 15. S7 评测台验证记录（2026-11-14，0 次真实 Tavily / 模型调用）

| 验证点 | 真实结果 |
|---|---|
| 一条命令出分 | `uv run python -m evals.run_eval` → `evals/scorecard.json`（6 组 A/B × 3 case = 18 次完整图运行），退出码 0 |
| golden 同步 | `build_golden --check` 通过；`evals/golden.jsonl` 28 行 = 1 meta + 3 case + 23 claim + 1 abstain，全部由 fixture + settings 规则派生 |
| baseline | `fact_accuracy=1.000`、`citation_traceability=1.000`、`abstain_rate=1.000`、`hallucination_rate=0.000`、`self_correction_success=1.0`、`avg_retry_rounds=1.000`；gate PASS |
| 可定位退化用例 | `self_correction_off` → `fact_accuracy=0.870`、`self_correction_success=0`，退化 id 精确为 `sparse:company:0/1/2` |
| A/B 如实判定 | `fewer_results` / `free_text_output` / `no_human_review` 三组标 `no_effect`（原因见 ACTION_PLAN 11.5），不伪造对照收益 |
| 负向对照 | `no_inline_citations` 故意关掉行内引用 → `fact_accuracy=1.000` 但 `citation_traceability=0.000`、`hallucination_rate=1.000`，23 条结论无可核验来源；常设防线防「引用被改坏却拿满分」 |
| CI 回归门禁 | 本地模拟 CI：`--compare evals/scorecard.json` → `PASS`、`degraded_case_ids=[]`；容差 0.02、方向 higher/lower、排除 `p95_latency_ms`；用例级比对覆盖所有共同 A/B 组 |
| 反向证伪 | 注入「Notion 已完成 IPO」→ `content_mismatch` 被抓；关掉引用 → 8 条 `no_explicit_citation`；伪造拒答 → `empty:company:abstain` 失败；A/B 组新增失败 → 回归门禁点名该组 |
| 可复现 | 两次独立评测的 `inputs_sha256` / `code_sha256` 与剔除 `elapsed_ms`/`p95` 后的全部字段逐字一致；scorecard 无时间戳 |
| 额度护栏 | `APP_MODE=live` 启动即拒；`socket.connect` 非回环连接立即抛错且作废结果；实测 `tavily=0 / llm=0 / blocked_connection_attempts=0` |
| 全量回归 | `121 passed`（S6 的 97 + S7 的 24）；`uv sync --frozen` 与 `uv pip check` 103 包兼容 |

**S7 复查补账（同日 18:56，详见 ACTION_PLAN 11.10）**：用户要求复查后，用真实探针坐实并修掉 8 项。最严重的是 **P1**——初版 `parse_report` 在没有 `[n]` 时从 golden 按文本反推 URL，导致关闭行内引用后 8 条无引用结论仍拿 `traceability=1.0`，等于用标准答案给报告补引用。现改为反推 URL 只作诊断并判 `no_explicit_citation`，`fact_accuracy` 与引用指标解耦，且新增 `no_inline_citations` 负向 A/B 组做常设防线。其余：P2 拆出 `code_sha256`、P3 修 golden 模拟轮数（1→3 与图一致）、P4 回归比对扩展到所有组、P5 样本不足拒绝出分、P6 指纹纳入自定义配置、P7 互斥参数报错、P8 修测试硬编码与恒真断言。同批探针复验：P1 `traceability=0.0 / fact_accuracy=1.0`、P3 `expected_research_runs=3`、P4 `passed=False + fewer_results:...`、P2 两个独立指纹。

## 16. S8.0 / S8.1 准备度记录（2026-11-14，0 次真实调用、0 credits）

| 项 | 实测 |
|---|---|
| 前置检查 | `--baseline-only` → `gate PASS`；`pytest -q` → `121 passed`（S6 97 + S7 24） |
| 凭据体检 | 当前进程所有模型 key / `TAVILY_API_KEY` / live 开关均 absent；`.env` 不存在，`.gitignore` 已覆盖密钥/DB/缓存；只打印存在性，未打印值 |
| 上游出网风险 | `/models`（`application.py:217-232`）确认会出网，本阶段不启动 FastAPI 因而不触发 |
| SDK 静态核对 | `inspect.signature(AsyncTavilyClient.search)` 的 `search_depth` / `topic` 字面量；项目 `advanced` / `finance` / `news` / `general` 全部合法；真实返回结构仍**未实测** |
| 修复的真实缺陷 | `TAVILY_DRY_RUN=true` 原仍无条件解析 `TAVILY_API_KEY` → 无 key 抛错，预演跑不通。现为独立 0 请求路径：不要 key、不要额度、强制 `DryRunSentinel`、预算须 `dry_run=True`；真实调用三重 opt-in 未放松 |
| S8.1 dry-run | 完整图 `research_runs=3`、`degrade`；12 条 query + sha256 cache key；`calls_made=0 / dry_runs=12 / blocked=0`；凭据三入口计数探针全 0；守卫已还原 |
| 可复现 | 两次独立运行逐字一致；`evals/live_dryrun.json` 与现场运行逐字一致；query 按稳定键排序（Send 并行派发顺序不作指标） |
| 额度推算 | 官方 `basic=1` / `advanced=2` credits/次、免费 1000/月；默认 advanced → 最坏 12×2 = 24 credits/公司；**推算值，实际扣 0**；官方未列单价的 depth 标 `null`，拒绝猜测 |
| 全量回归 | `135 passed`（97 + 24 + 14）；`uv pip check` 兼容；工作区干净 |

**S8.0/S8.1 如实边界**：不产出任何真实准确率 / 幻觉率 / 延迟 / 成本 / 真实检索语料；
`scorecard.json` 的 `1.000` 仍只是 fixture 契约回归分。用户已于同日 21:20 拍板
（模型 key、Tavily 额度、真实 golden），S8.2 已执行，见第 17 节。
本节保留为当时 0 调用状态的历史快照。详见 `docs/LIVE_READINESS.md`
与 `docs/ACTION_PLAN.md` 12.6 / 12.7。

## 17. S8.2 单次真实实测记录（2026-11-14，1 次调用 / 2 credits）

| 项 | 实测 |
|---|---|
| 阿里云适配（0 调用） | `config/loader.py` 增 `dashscope` provider、`LLM_PROVIDER` 锁定不回退、`LLM_BASE_URL` 覆盖；`settings.yaml` 模型角色改 `${LLM_MODEL:-...}`（默认值不变）；`tests/test_s8_dashscope.py` 10 例验证 `qwen-plus` + DashScope 端点，MockTransport + 禁网守卫 0 连接 |
| 用户 key 体检 | 用户级变量名是 `SYSTEM_ALIYUN_APIKEY`（长度 117）、`BASE_URL` 指向 DashScope 兼容端点；当前进程未继承，运行时映射为 `DASHSCOPE_API_KEY` 注入内存，不落盘、不打印、不提交 |
| 单次真实检索 | `evals/live_probe.py`：`CallBudget(1)` + `RecordingClient` 双上限；`calls_made=1`、`sdk_invocations=1`、`cache_hits=1`（第二次命中缓存 0 额外扣费） |
| 返回结构 | 顶层 `query/follow_up_questions/answer/images/results/response_time/request_id`；`results` 3 条，含 `url/title/content/score`（另 `id`、`raw_content=None`）；`contract_ok=true` |
| Document 契约 | `documents_from_results` 转出 3 个，`metadata_keys=[score,section,source,title,url]`，全部有 URL；score `0.7174–0.8146`、content `794–2011` 字符 |
| 计费 | `advanced` 2 credits/次 × 1 = **2 credits（官方规则推算，非账单）**；用户放行上限 20，剩余未动 |
| 脱敏 | `evals/live_probe.json` 只含结构统计，无正文 / 完整 URL / 密钥串（正则核对 `tvly-`、`sk-` 均无）；真实响应缓存在 gitignored `evals/cache/tavily/` |
| 真实 golden 草稿 | `evals/golden_live_draft.jsonl` 25 条候选（5 家×5），全部 `pending_human_review`、`human_verified_claims=0`、7 处来源冲突如实列出；`tests/test_s8_golden_draft.py` 7 例阻止草稿被接进评测台 |
| 全量回归 | `160 passed`（97+24+14+10+8+7）；golden `--check` 同步；scorecard 重生成门禁 `PASS`；`uv pip check` 103 包兼容 |

**如实边界**：**0 次真实模型调用**（`qwen-plus` 的 `with_structured_output` 只做了
0 调用构造验证）；1 次请求 / 1 家公司 / 1 栏目，不产出 p95、平均成本或稳定性；
真实 golden 未经人工复核，**不是标准答案**；S7 逐字匹配口径对真实报告不适用
（S8.4 需语义 judge）。**累计仍未产出任何真实准确率 / 幻觉率 / 延迟 / 成本数字**，
简历效果数字必须等 S8.3 之后可复现实测。

**S7 如实边界（最重要）**：这是**合成语料上的契约回归测试**，不是模型能力评测。golden 与被测系统读同一份 fixture，baseline 满分是「按规范把给定文档搬进报告并加对引用」的必然结果，**不得写成「准确率 100%」进简历**。`citation_traceability` 是词法包含代理而非语义蕴含；`hallucination_rate` 是它的互补值而非独立证据；`cost_per_report=0`、`p95_latency_ms` 为本机耗时，都不是真实成本/延迟。原计划「30–50 家真实公司 × 5 事实」的 golden 未做（无 key / 无真实语料，硬编即造假），归 S8；换 `EVAL_DATASET_PATH` 即可复用脚本。`no_inline_citations` 组的 `hallucination_rate=1.0` 属「故意关掉引用」的负向对照，不是默认配置的幻觉率。内容级语义 judge、真实指标、S9 简历仍未开工。

## 18. S8.3 AI 辅助复核 + 首轮端到端真实实测（2026-11-14 22:37 起）

> 第 13–17 节是各阶段当时的历史快照，保留不改；**当前累计以本节与
> `docs/LIVE_FINDINGS.md` 为准**：4 次真实 Tavily 检索（8 credits）、5 次模型请求。

| 项 | 实测结果 | 产物 / 依据 |
|---|---|---|
| AI 辅助复核 | 9 个原始 URL 逐条打开原文；`verified=15 / needs_fix=8 / reject=2`；3 个 URL 打不开；2 处冲突用官方一手来源查清 | `evals/golden_live_review.jsonl`、`docs/GOLDEN_REVIEW.md` |
| 人工核验状态 | **仍是 0**：25 条 `user_verdict` 全 `null`，`human_verified_claims=0` | `tests/test_s8_golden_review.py` 8 例锁死 |
| 模型兼容 | `qwen-plus` + `function_calling` 返回合规 `SectionBrief`，3 条 fact URL 全可回溯；1 次请求 / 748 tokens / 3.8 s | `evals/llm_probe.json` |
| 端到端真实报告 | Notion：3 次检索 + 1 缓存命中 = **6 credits**（累计 **8/50**）；4 次模型请求 / 7896 tokens；62.9 s；4998 字符 / 27 结论 / 11 引用 / 四栏目齐全 / 无降级 | `evals/live_run.json` |
| 硬预算 | `TAVILY_MAX_CALLS=12` + `CallBudget(12)`，累计超 50 直接作废；实际 `remaining=9` | 同上 `budget` / `credits` |
| 失败案例 | 词法检查自动抓到 `Company Overview` 里 founded in **2013 vs 2014** 硬矛盾；人工另见「总部伦敦」等未核验表述；来源含 `medium.com` | `evals/live_quality.json` |
| 引用完整性 | `citation_integrity_ok=true`（27 个 `[n]` 都有对应编号）——**只证明编号齐全，不证明事实正确** | 同上 |
| 脱敏 | 三个产物均通过 `sk-` / `tvly-` 正则扫描；密钥只在进程内存注入；缓存 4 份在 gitignored `evals/cache/` | 提交前核对 |

**如实边界（最重要）**：1 家公司 1 次运行，**没有**真实准确率 / 幻觉率 / p95 / 成本单价
（`total_cost_usd=null`，qwen-plus 不在 OpenAI 价目表内，不套用不编造）；
真实报告出现自相矛盾，说明 S7 fixture 的 `1.000` 只是流程回归分，**不能当准确率写进简历**；
25 条 golden 未人工核验，S7 逐字匹配对真实报告失效，S8.4 必须先解决语义 judge。
剩余 42 credits 未动；S8.4–S8.6、S9 简历仍未开工。
