# AGENT.md — 本项目编程规范

> 任何 AI 编码会话、任何人工提交，在修改本仓库代码前都必须读完本文件与 `docs/PROJECT_PLAN.md`、`docs/ACTION_PLAN.md`。
> 本规范的目的是：**防止改造过程把项目写回「浅用框架」的老路**。

## 1. 项目一句话

基于 `guy-hartstein/company-research-agent`（Apache-2.0）二次开发，把线性 DAG 公司调研流水线改造成带自纠正回路、可溯源、可回归评测的 LangGraph 状态工作流。

## 2. 归因（红线）

- 保留原仓库 `LICENSE`、版权声明与 fork 来源，不得删除或改写。
- README、简历、commit message 一律写明「基于 XX（Apache-2.0）二次开发」。
- 禁止把原版已有功能（四路并行检索、Tavily 筛选、PDF 导出、SSE 进度）描述成独立设计。
- 禁止写「独立开发」「生产上线」「服务 X 万用户」。

## 3. 技术栈

- Python 3.11+，async-first，全量 type hints
- 依赖唯一真源：`pyproject.toml` + `uv.lock`（解析 106 包 / 实装 103 包）；`requirements.lock.txt` 只是 S1 阶段的 pip 快照，不作准
- 实测锁定版本：`langchain 1.3.9` / `langchain-core 1.8.0` / `langgraph 1.2.22` / `langgraph-checkpoint 4.3.2` / `langgraph-checkpoint-sqlite 3.1.3` / `pydantic 2.14.3`
- `langgraph` 原仓库仅为传递依赖，本项目已在 `pyproject.toml` 中**显式声明**
- **虚拟环境由 uv 管理**：`.python-version=3.11`，`.venv` 由 `uv venv --python 3.11` 创建；所有命令统一 `uv run python ...`，禁止直接 `pip install` 改环境
- `langgraph.json` 的 `dependencies: ["."]` 依赖 `pyproject.toml` 可安装包，删掉 pyproject 会让 LangGraph Server 失效
- Pydantic v2（结构化输出与配置模型）
- **State 的 TypedDict 必须从 `typing_extensions` 导入**：原版 `backend/classes/state.py` 用 `typing.TypedDict`，在 Python 3.11 + pydantic 2.14 下 schema 内省会抛 `PydanticUserError`（见 `docs/BASELINE.md` 第 3 节）
- **LangGraph 1.2 的 `get_input_schema()` 只列外部输入 channel，完整字段要用 `get_output_schema()`**；测试两者都要覆盖
- 持久化：`AsyncSqliteSaver`（`langgraph.checkpoint.sqlite.aio`）落盘 / S8 再切 Postgres。同步 `SqliteSaver` 的 `aget_tuple` 抛 `NotImplementedError`，**不能用于 async 图**
- 配置：YAML + 环境变量；测试：pytest + pytest-asyncio；CI：GitHub Actions

## 4. 运行模式

- `APP_MODE=fixture`（默认）：不依赖任何 API key，用 `evals/fixtures/tavily_responses.json` 与确定性 stub 跑通全链路，结果可复现。
- `APP_MODE=live`：真实 OpenRouter/OpenAI + Tavily + DB。
- **切换只允许改 `.env`，禁止改代码分支判断散落在业务节点里**；模式差异统一由 `config/loader.py` 与能力层适配。
- 配置统一经 `config.loader.get_settings()` 获取，业务代码禁止直接读 yaml / `os.environ`。
- `features.*` 四项开关必须可由 `FEATURES_*` 环境变量覆盖；`config/eval.yaml` 的 `ab_tests[].overrides` 一律经 `config.loader.apply_overrides()` 应用（点号路径，非法路径直接抛错），禁止评测脚本自己改 yaml 或对象字典。
- `features.structured_output` / `human_review` 当前只做配置占位，代码消费分别在 S5 / S6，不得写成已实现。

## 5. Python 代码风格

- 所有节点函数 `async def`，签名统一 `(state: ResearchState) -> dict[str, Any]`；需要配置时用**节点工厂闭包**注入：`def make_xxx_node(settings: Settings) -> Callable`，不要往签名里塞 keyword-only 参数（LangGraph 不认）。
- 节点是**纯函数**：只读 State、返回字段字典；禁止就地修改传入 State、禁止写全局可变状态（原版 `job_status` 全局字典只允许在 API 适配层使用）。
- 日志用 `logging`，业务节点禁止 `print`；**CLI 入口（`graph/run.py`）允许 print 结构化结果**。禁止裸 `except: pass`，异常必须记录或向上抛。
- 所有阈值、上限、模型名、路径、开关一律从配置读，**禁止硬编码魔法数字**。
- 密钥只从环境变量读，禁止写进代码、yaml、日志或 commit。

## 6. LangGraph 硬性约定（逐条可检查）

1. `StateGraph` 的 schema **只能**是 `ResearchState`（`InputState` 仅用于外部入参）。
2. 任何跨节点写入的字段必须在 `ResearchState` 中声明。
3. 并行节点写同一字段**必须**用 `Annotated[..., reducer]`；`messages` 用 `add_messages`，文档字典用按 URL 去重的 `merge_docs`，禁止直接 `operator.add` 到 dict。
4. **禁止在节点内部用 `asyncio.gather` 做本该由图编排的并行**（原版 `briefing.py` 的做法）；并行一律用并行边或 `Send`。
5. 任何循环**必须**有 `retry_count` 上限（默认 2）与明确降级出口；禁止用「模型自己说够了」当终止条件。
6. 回退必须精确控制重搜范围，禁止唤醒全部 analyst。S4 用 `Send` 按 `sections_to_research` 白名单动态派发（见 `graph/subgraphs/research.py`）：**`Send` 从 `langgraph.types` 导入**，`langgraph.constants` 在 1.2.22 已弃用。
7. `compile()` **必须**传 `checkpointer`；`interrupt()` 必须与 checkpointer 同时存在；统一走 `persistence.CheckpointSession.compile()`。**例外一**：子图 `compile()` 不另传，运行时继承父图 saver；且子图必须用 `StateGraph(..., input_schema=..., output_schema=...)` 隔离累积字段，否则 `review_notes` 会被主图 reducer 重复累加（S4 实测踩到）。`input`/`output` 旧参数名已弃用。**例外二**：`langgraph_entry.py` 供 LangGraph Server 加载，模块顶层无法 `await` `AsyncSqliteSaver.from_conn_string()`（它是 async context manager），故由 Server 注入 saver；该例外**只适用于这一个文件**，CLI 与 `application.py` 仍必须走 `CheckpointSession`。
8. `thread_id` 由 `config.loader.build_thread_id()` 按配置模板生成，禁止硬编码或留空。
9. 条件函数保持无副作用、可单测：给定 State → 返回分支名字符串。
10. 每个节点、每条条件边必须有对应 pytest 用例；新增边不改测试视为未完成。
11. 主图节点名 `research` 保持不变（内部是子图），CLI 轨迹统计与回归用例依赖该名字；子图的派发字段（`active_section` 等）不得污染 `ResearchState`，子图输出字段必须是主图字段的子集且同名 reducer。
12. 栏目级重试下，检索轮次**只能**取 `retry_count[active_section]`，禁止 `max(retry_count.values())`（S4 复查实测：各栏目不同步回退时会错拿别的栏目轮次的数据）。回退留痕用每栏目字典，不写单一 `round`。
13. `*_data` 按 URL 累积是「保留旧证据」的设计取舍；`replace_mapping` 只在「同 URL 新版本被判低分/无 URL」时移除旧引用。文档与测试**不得**写成「旧引用自动移除」，也不得用手工构造空 State 绕开真实 reducer 链来自我证明。
14. `interrupt()` 必须与真实 checkpointer 同时存在；默认 `FEATURES_HUMAN_REVIEW=false`，开关关闭时 `build_graph` **不得注册** `human_review` 节点（`test_s4_subgraph.py:97` 精确断言主图 7 节点）。`auto_approve_review=true` 是无人值守默认值，避免 `/research` 永久卡在中断。
15. resume 决策必须是受控 dict（`approved / rejected_sections / note`）：非法值 fail-safe 成「不批准」，栏目走白名单过滤且去重；人工否决只追加 `degraded_sections` 并复用拒答文案，**不得生成新结论**。恢复靠 `Command(resume=...)` + 同一 `thread_id` 的磁盘 checkpoint，不靠进程内变量；节点恢复时会重跑，因此 `interrupt()` 前不得有副作用。

## 7. LangChain 硬性约定

1. 用 LCEL 组装链路：`ChatPromptTemplate | model | parser`。
2. 结构化数据一律 `with_structured_output(PydanticModel)`，**禁止裸 `json.loads`**。
3. 外部数据源必须封装成 `BaseRetriever` 或 `@tool`；禁止在节点里 `new AsyncTavilyClient`（原版 `base.py` L24 的做法）。
4. 模型名 / 温度 / 重试次数**只能**来自 `settings.models`；凭据经 `config.loader.resolve_llm_credentials()`，用 `SecretStr` 且**不进 `Settings`**（避免 `model_dump` / 日志泄密）。禁止复用上游 `backend/llm.py`（硬编码模型名 + 直接 `os.getenv`）。缺 key 必须明确抛错，禁止悄悄回退 fixture。
5. 无 key 测试 `with_structured_output` **只能**用 `httpx.MockTransport` 注入 `http_async_client`（实测 `GenericFakeChatModel` 抛 `NotImplementedError`）；mock 的 `base_url` 必须指向不可达本地端口，保证完全离网。mock 结果不得写成真实模型能力或指标。
6. `Fact.source_url` 必须属于本次传入文档集合，否则剔除并写 `review_notes`；校验失败重试 `models.max_retries` 次后整栏降级留痕，**禁止静默丢字段**。URL 级回溯不等于内容级 `citation_traceability`（S7）。
4. 模型统一经 `create_llm(role, config)` 获取，角色分为 `research / briefing / editor / judge`。
5. 抽取校验失败 → 重试一次 → 仍失败则该栏目降级并记入 `review_notes`，**禁止静默丢字段**。
6. 禁止在 prompt 中写 `Never mention "no information found"` 这类迫使模型编造的指令。原版 `backend/prompts.py` 仍保留该指令（上游原文件，未删），但 **S3 新图完全不加载它**；S5 接真实模型时也不得复用。
7. **Tavily 免费额度是红线**：真实检索必须同时满足 `APP_MODE=live` + `TAVILY_LIVE_ENABLED=true` + `TAVILY_MAX_CALLS>0`；`CallBudget` 硬计数先于请求，缓存优先、dry-run 不发请求。测试 / CI / 演示**禁止构造 `AsyncTavilyClient`**，一律注入 fake。key 只经 `config.loader.resolve_tavily_credentials()` 解析，不接收请求体 key、不写日志、不写进 `.env`。任何真实调用次数必须能被测试核对。
8. fixture 模式可用本地 `httpx.MockTransport` 真跑 LCEL，但文档与注释必须写明「确定性 stub，非模型能力」。mock handler 取消息时按 `role in ("user", "human")`（OpenAI 请求体是 `user`），否则会静默抽不出事实误判降级。`features.structured_output=false` 的报告必须与 S4 模板逐字一致，作为 A/B 基线；节点内传递引用编号用显式参数，禁止模块级全局可变变量。
9. **简报后端的 client 所有权归「一次图运行」**：`make_briefing_backend()` 会创建 `httpx.AsyncClient`，短生命周期路径（CLI / `/research`）必须经 `briefing_backend_scope()` 注入 `build_graph(..., briefing_backend=...)` 并在 `finally` 里 `aclose()`；Studio 是模块级单例、随 Server 进程存活，不走 scope。异常路径同样要关，长驻服务不得每请求泄漏一个 client。
10. fixture stub 的 `Fact.confidence` **必须来自文档 `score`**（缺失/越界夹到 `[0,1]`，不伪造），且 `score` 要真的进 prompt；禁止在 mock handler 里硬编码 0.9，否则 S7 拿置信度做评测会失真。

## 8. 可溯源约定

- 每条 `Fact` 必须带非空 `source_url` 与 `confidence`。
- 报告正文必须生成行内引用；末尾 References 与正文引用来自**同一份** `references` 字典。
- 证据不足或重试超限：输出「该类信息未找到公开依据」并置 `degraded=True`，不得编造。
- 正文事实性结论与末尾 References **共用同一份选中文档并统一编号**；`report.max_references` 是每栏目结论上限，超量截断必须写进 `review_notes`。禁止出现没有 `[n]` 的事实性结论（拒答句除外）。
- 「引用同源」只保证编号能对回来源，**不等于「来源支持该结论」**；内容级 `citation_traceability` 由 S7 的 judge / golden set 度量，S3 不得宣称已实现。

## 9. 评测与数字（红线）

- 任何指标只能由 `evals/run_eval.py` 产出，禁止手写、估算或引用无来源数字。
- 新增节点 / 边 / 配置开关，必须同步新增用例与 A/B 项。
- `evals/scorecard.json` 每次评测后提交；CI 核心指标回退超过 `config/eval.yaml` 容差即失败。
- 简历与文档中的数字一律先写 `X`，跑完实测再替换，且必须能指到对应 scorecard 与 commit。
- 每组 A/B 必须先经 `apply_overrides()` 从基线 Settings 派生；路径写错要立刻失败，不得静默忽略后照常出分。

## 10. 目录约定

| 路径 | 职责 |
|---|---|
| `backend/` | 原仓库代码，二次开发，尽量少动 UI/API |
| `graph/` | 主图、research 子图、条件函数、降级节点、State 定义 |
| `capabilities/` | Retriever、LLM 工厂、Pydantic schema、引用渲染 |
| `persistence/` | checkpointer、thread_id |
| `evals/` | golden set、fixtures、指标脚本、scorecard |
| `baseline/` | 上游基线采集脚本与机器可读结果（只读，不改） |
| `tests/` | 每节点/每条件函数一个用例文件 |
| `config/` | settings.yaml、eval.yaml、loader.py |

禁止把新代码继续堆进 `backend/nodes/` 而不分层。

## 11. 提交规范

- Conventional Commits：`feat(graph): ...`、`fix(reducer): ...`、`eval: ...`、`docs: ...`
- 一次提交一个逻辑改动；评测 scorecard 随对应代码改动一起提交。
- 提交前自检：无 `.env`、无密钥、无硬编码数字、LICENSE 未被改动、测试通过。

## 12. 常用命令

```bash
# 首次落地 / 换机器（读 .python-version + uv.lock，幂等）
uv sync

# 新增依赖（会同时更新 pyproject.toml 与 uv.lock）
uv add <package>          # 开发依赖用 uv add --dev <package>

# 运行测试 / 脚本（一律走 uv run，禁止直接调 .venv 里的 python）
uv run python -m pytest -q
uv run python baseline/inspect_upstream.py
uv run python -c "from config.loader import get_settings; print(get_settings().app.mode)"

# 依赖完整性自检
uv pip check

# S3 自纠正回路三条验收场景（无需 key）
uv run python -m graph.run --case sufficient --show-report --trace
uv run python -m graph.run --case sparse --show-report --trace
uv run python -m graph.run --case empty --show-report --trace

# A/B：命令行直接关掉自纠正回路（应看到 research_runs=1、degraded=true）
FEATURES_SELF_CORRECTION=false uv run python -m graph.run --case sparse --trace

# 后续实现后启用：
# uv run python -m graph.run --company Notion
# uv run python -m evals.run_eval --config config/eval.yaml
# APP_MODE=live uv run python -m evals.run_eval --config config/eval.yaml
```

`uv` 默认走官方 PyPI（已在 `pyproject.toml` 的 `[[tool.uv.index]]` 固定）；本机 `pip.ini` 指向的清华镜像返回 `from versions: none`，**不要**给 uv 配成该源。

## 13. 禁止清单（速查）

- ❌ `StateGraph(InputState)` / 裸 `compile()` / 无 reducer 的并行写
- ❌ 同步 `SqliteSaver` 配 async 图（`aget_tuple` 不支持）/ `InMemorySaver` 冒充持久化
- ❌ 节点内 `asyncio.gather` 代替图并行
- ❌ 无上限循环、无降级出口
- ❌ 裸 `json.loads` 当结构化输出
- ❌ 节点内直接 new 第三方 client
- ❌ `Never mention "no information found"` 类 prompt
- ❌ 无来源的事实、无脚本支撑的指标
- ❌ 硬编码密钥、阈值、模型名、thread_id
- ❌ 把二次开发写成独立开发
- ❌ 直接 `pip install` 改环境、手写依赖版本却不同步 `uv.lock`
- ❌ 给会被回退/并行重复写入的 dict/list 字段不配 reducer
- ❌ `from langgraph.constants import Send` / 子图把累积字段带回主图 / 随意改主图节点名破坏轨迹统计
- ❌ 栏目级回退用全局 `max(retry_count.values())` 当检索轮次 / 把「旧引用可移除」写成无条件的结论
- ❌ 硬编码模型名 / 业务代码直接 `os.getenv` 读 key / 把凭据放进 `Settings` / 缺 key 悄悄回退 fixture
- ❌ 用 `GenericFakeChatModel` 测 `with_structured_output` / mock HTTP 指向可达外网 / 把 mock 结果写成真实模型指标
- ❌ 用真实 Tavily / 模型额度跑测试或演示 / 绕过 `CallBudget` 发包 / 把请求体传入的 key 当凭据
- ❌ 模块级全局可变变量传递引用编号 / 把 fixture 确定性 stub 说成模型能力 / 谎称 live 已实测
- ❌ `build_graph()` 自建 briefing backend 却不 `aclose()` / fixture stub 硬编码 `confidence` / 把「0 次外部调用」只写在文档里而不落测试
- ❌ 无 checkpointer 的 `interrupt()` / 默认开启人工复核让 `/research` 永久暂停 / 人工否决后仍输出原结论或留无引用事实
