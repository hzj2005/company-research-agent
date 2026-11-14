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
- 实测锁定版本（见 `requirements.lock.txt`）：`langchain 1.3.9` / `langchain-core 1.8.0` / `langgraph 1.2.22` / `langgraph-checkpoint 4.3.2` / `langgraph-checkpoint-sqlite 3.1.3` / `pydantic 2.14.3`
- `langgraph` 原仓库仅为传递依赖，本项目已**显式安装**；运行统一用项目内 `.venv/Scripts/python.exe`
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

## 5. Python 代码风格

- 所有节点函数 `async def`，签名统一 `(state: ResearchState) -> dict[str, Any]`；需要配置时用**节点工厂闭包**注入：`def make_xxx_node(settings: Settings) -> Callable`，不要往签名里塞 keyword-only 参数（LangGraph 不认）。
- 节点是**纯函数**：只读 State、返回字段字典；禁止就地修改传入 State、禁止写全局可变状态（原版 `job_status` 全局字典只允许在 API 适配层使用）。
- 日志用 `logging`，禁止 `print`；禁止裸 `except: pass`，异常必须记录或向上抛。
- 所有阈值、上限、模型名、路径、开关一律从配置读，**禁止硬编码魔法数字**。
- 密钥只从环境变量读，禁止写进代码、yaml、日志或 commit。

## 6. LangGraph 硬性约定（逐条可检查）

1. `StateGraph` 的 schema **只能**是 `ResearchState`（`InputState` 仅用于外部入参）。
2. 任何跨节点写入的字段必须在 `ResearchState` 中声明。
3. 并行节点写同一字段**必须**用 `Annotated[..., reducer]`；`messages` 用 `add_messages`，文档字典用按 URL 去重的 `merge_docs`，禁止直接 `operator.add` 到 dict。
4. **禁止在节点内部用 `asyncio.gather` 做本该由图编排的并行**（原版 `briefing.py` 的做法）；并行一律用并行边或 `Send`。
5. 任何循环**必须**有 `retry_count` 上限（默认 2）与明确降级出口；禁止用「模型自己说够了」当终止条件。
6. 回退用 `Command(goto=...)` 精确指向目标节点，禁止用无条件边唤醒全部 analyst。
7. `compile()` **必须**传 `checkpointer`；`interrupt()` 必须与 checkpointer 同时存在；统一走 `persistence.CheckpointSession.compile()`。
8. `thread_id` 由 `config.loader.build_thread_id()` 按配置模板生成，禁止硬编码或留空。
9. 条件函数保持无副作用、可单测：给定 State → 返回分支名字符串。
10. 每个节点、每条条件边必须有对应 pytest 用例；新增边不改测试视为未完成。

## 7. LangChain 硬性约定

1. 用 LCEL 组装链路：`ChatPromptTemplate | model | parser`。
2. 结构化数据一律 `with_structured_output(PydanticModel)`，**禁止裸 `json.loads`**。
3. 外部数据源必须封装成 `BaseRetriever` 或 `@tool`；禁止在节点里 `new AsyncTavilyClient`（原版 `base.py` L24 的做法）。
4. 模型统一经 `create_llm(role, config)` 获取，角色分为 `research / briefing / editor / judge`。
5. 抽取校验失败 → 重试一次 → 仍失败则该栏目降级并记入 `review_notes`，**禁止静默丢字段**。
6. 禁止在 prompt 中写 `Never mention "no information found"` 这类迫使模型编造的指令。

## 8. 可溯源约定

- 每条 `Fact` 必须带非空 `source_url` 与 `confidence`。
- 报告正文必须生成行内引用；末尾 References 与正文引用来自**同一份** `references` 字典。
- 证据不足或重试超限：输出「该类信息未找到公开依据」并置 `degraded=True`，不得编造。

## 9. 评测与数字（红线）

- 任何指标只能由 `evals/run_eval.py` 产出，禁止手写、估算或引用无来源数字。
- 新增节点 / 边 / 配置开关，必须同步新增用例与 A/B 项。
- `evals/scorecard.json` 每次评测后提交；CI 核心指标回退超过 `config/eval.yaml` 容差即失败。
- 简历与文档中的数字一律先写 `X`，跑完实测再替换，且必须能指到对应 scorecard 与 commit。

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
# 运行测试（必须用项目 venv）
.venv/Scripts/python.exe -m pytest -q

# 重新采集上游基线（不联网，占位 key）
.venv/Scripts/python.exe baseline/inspect_upstream.py

# 校验配置解析
.venv/Scripts/python.exe -c "from config.loader import get_settings; print(get_settings().app.mode)"

# 后续实现后启用：
# .venv/Scripts/python.exe -m graph.run --company Notion
# .venv/Scripts/python.exe -m evals.run_eval --config config/eval.yaml
# APP_MODE=live .venv/Scripts/python.exe -m evals.run_eval --config config/eval.yaml
```

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
