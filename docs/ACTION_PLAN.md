# 行动方案：按步执行清单

> 本文把任务清单 #1–#9 转成「一步一验收」的执行序列。每完成一步，更新状态并留下可查的产出物。
> 制定日期：2026-11-14 | 设计依据：`docs/PROJECT_PLAN.md`、`AGENT.md`

---

## 0. 环境事实（已实测，不是假设）

| 项 | 实测结果 | 对执行的影响 |
|---|---|---|
| Python | WorkBuddy 内置 3.13.14 / `D:\Python\Python311` 等 4 个解释器 | 用 3.11 建独立 venv，兼容性最好 |
| 包管理 | `uv 0.8.15` 已装；`uv.lock` + `pyproject.toml` 已生成 | 命令统一 `uv run` |
| pip 镜像 | `pypi.tuna.tsinghua.edu.cn` **返回 `from versions: none`，不可用** | 统一改用 `-i https://pypi.org/simple`（已实测可装 PyYAML） |
| 关键依赖 | 全局环境 langchain / langgraph / pydantic / pytest **全部 MISSING** | 必须建独立 venv 装依赖，否则任何「跑通」都是空话 |
| 上游仓库 | 本地已有快照，commit `23fe92d`（2026-10-26），含 `LICENSE`、`.git`、多语言 README | 可直接落地，保留 fork 来源与 commit 历史 |
| API key | 用户暂时没有模型 / Tavily key | `fixture` 模式跑通链路；`live` 真实实测延后到 Step 8，未跑通前不写任何指标数字 |

**归因红线**：本项目基于 `guy-hartstein/company-research-agent`（Apache-2.0）二次开发。所有步骤都保留 `LICENSE` 与上游 commit，README/简历不得写「独立开发」。

---

## 1. 执行序列

| Step | 任务 | 具体动作 | 产出物 | 验收标准 | 状态 |
|---|---|---|---|---|---|
| **S0** | #10 #11 #12 | 方案、规范、双模式配置 | `PROJECT_PLAN.md` / `AGENT.md` / `.env.example` / `config/*.yaml` | 文件存在 | ✅ 已完成 |
| **S1** | **#1 基座落地与原版 baseline** | ① 原仓库落到工作区，保留 LICENSE + 上游 commit + attribution<br>② 建独立 venv，从官方 PyPI 装齐依赖<br>③ 补做阶段 0 欠账：`yaml.safe_load` 全量解析校验<br>④ 真正 import 并编译原版 `StateGraph`，导出节点/边清单<br>⑤ 记录 baseline 报告结构与耗时口径 | `backend/`、`LICENSE`、`docs/UPSTREAM.md`、`docs/BASELINE.md`、`.venv/`、`requirements.lock.txt` | 原版图对象能编译；两份 YAML 全量解析通过；baseline 文档有代码位置依据 | ✅ 已完成（可达部分；live 调研剥离为 #13） |
| **S2** | #2 状态契约 | `StateGraph(ResearchState)` + `add_messages` / `merge_docs` reducer；`compile(checkpointer=...)` 接真实 SQLite Saver；`thread_id` 按模板 | `persistence/`、`graph/state.py`、单元测试 | 进程重启后同一 thread 可恢复；并行写回不覆盖；恢复前后 State 一致 | ✅ 已完成（10 个 pytest 全通过） |
| **S3** | #3 自纠正回路 | `evidence_check` 判定 + `add_conditional_edges` + `retry_count<=2` + `degrade` 降级拒答 | `graph/conditions.py`、`graph/nodes/`、`graph/builder.py`、`graph/run.py`、3 类 fixture 用例 | sparse 样本触发回退并在 2 轮内收敛；empty 样本输出「无公开依据」且不编造 | ✅ 已完成（23 passed） |
| **S4** | #4 并行与子图 | `research` 换成编译子图，`dispatch` 用 `Send` 按白名单精确派发 4 analyst | `graph/subgraphs/`、白板图（第 7.5 节） | 主图 7 节点可完整画出；reducer 合并可验证 | ✅ 已完成（43 passed，见第 7.7 节） |
| **S5** | #5 LangChain 深化 | Tavily 封 `BaseRetriever`；`with_structured_output` + 字段置信度 + 校验重试；行内引用 | `capabilities/`、Pydantic schema | 每条 Fact 能对回 source_url；抽取失败自动重试不静默丢字段 | ✅ 完成（8.1–8.5，见 8.7 / 9.6；**仅 fixture，live 实测归 S8**） |
| **S6** | #6 HITL | 成稿前 `interrupt()` 复核 + `Command(resume=...)`；复核留痕导出标注 | `graph/nodes/human_review.py` | 中断→恢复后 State 一致；依赖真实 checkpointer | ✅ 完成（10.1–10.4，见 10.5；仅 fixture） |
| **S7** | #7 评测台 | ~~30–50 真实公司~~ → fixture 派生 golden（3 场景 / 23 claim / 1 拒答）、8 项指标、4 组 A/B、scorecard、CI | `evals/`、`.github/workflows/eval.yml` | 一条命令出分，能定位退化用例 | ✅ 完成（11.1–11.9，仅 fixture；**真实 golden 归 S8**） |
| **S8** | #8 真实实测 | 切 `APP_MODE=live`，真实模型 + 真实 Tavily + 真实 DB 跑全量 | 对比表、失败案例、成本/延迟取舍 | 每个数字能由脚本与日志当场复现 | 🟢 S8.0–S8.6 全部完成（累计 8/50 credits、6 次模型请求、1 份真实报告、25 条人工核验 golden、1 次真实语义 judge、fixture vs 真机对比表、30 条可复现简历数字出处表，见 `docs/LIVE_REPORT.md` / `docs/RESUME_EVIDENCE.md`）；S9 已完成，见 12.18 |
| **S9** | #9 简历交付 | 3–4 条描述 + 面试追问清单 | `docs/RESUME.md` | 每条能指到具体文件与 commit | ✅ 完成（12.16 规划 / 12.18 执行）：4 条描述 + 18 条追问，数字全部由出处表插值，`tests/test_s9_resume.py` 17 条护栏 |
| **S10** | #10 质量修复（S9 之后追加） | 同名实体消歧 + 同栏目冲突前置 | `capabilities/entity_guard.py`、`capabilities/conflict.py`、`graph/nodes/collect.py`、`graph/nodes/report.py` | 真机三类硬伤里的两类被堵住，且不误杀 | ✅ 完成（12.20）：真实缓存回放 12 篇 → 拒 2 篇，References 11 → 9；56 条新护栏 |
| **S11** | #11 按岗位出多版措辞（S9 之后追加） | 同一批事实句按 Agent / RAG / 后端三种视角重排，不改写事实 | `evals/build_resume_variants.py`、`docs/RESUME_VARIANTS.md` | 三版排法必须真的不同，且粘贴行与 `docs/RESUME.md` 逐字一致 | ✅ 完成（12.22）：三个方向 × 三条，14 条新护栏；顺手补上 D 组漏渲染与一处归因不准 |
| **S12** | #12 持久化换 Postgres（S11 之后追加） | checkpoint 与任务台账搬 Postgres，SSE 进度仍留内存 | `persistence/checkpointer.py`、`persistence/job_store.py`、`persistence/setup_postgres.py`、`persistence/migrate_sqlite_to_pg.py` | 重启后同一 job 与存档仍可查；无库时测试整组跳过而非误通过 | ✅ 完成（12.23 / 复查 12.24）：**502 passed**、13 条 PG 用例、旧存档 11→11 状态一致；运行手册 `docs/POSTGRES.md` |
| **S13** | #13 前端瘦身（S12 之后追加） | 按「后端会不会发这个事件」删无用面板与表单，界面改中文，加模式标签 | `ui/src/App.tsx`、`ui/src/components/`、`ui/src/index.css` | 构建通过 **且**真点一遍能出报告；删掉的每个组件都要能指出「它永远不会显示」 | ✅ 完成（12.33）：13 组件 → **5 个**、源码 3300 → **560 行**、JS 532 → **306 kB**；CDP 实测出 5622 字报告，**0 credits** |

**顺序约束**：S2 是 S3/S4/S5/S6 的前置（都要改 `graph.py` / `state.py`），必须串行；S6 依赖 S2 的 checkpointer；S8 依赖 S7 且需要 key。

---

## 2. 本轮（S1）的细分动作与验收

1. **落地**：复制上游快照到工作区根（原仓库的 `backend/` 正好对应方案里的 `backend/`），冲突文件 `.env.example` 另存为 `docs/upstream.env.example`；保留 `.git` 并把 remote 改名 `upstream`，让后续每个改动都能 `git diff` 到原版。
2. **归因**：写 `docs/UPSTREAM.md`，记录来源 URL、commit SHA、License、SHA256、落地时间、原版文件清单。
3. **环境**：`.venv`（Python 3.11）；按 `requirements.txt` + 显式 `langgraph` / `pytest` 安装，源用 `https://pypi.org/simple`；导出 `requirements.lock.txt`。
4. **补校验**：用真实 `yaml.safe_load` 解析 `config/settings.yaml` 与 `config/eval.yaml`，把结果写进 `docs/BASELINE.md`，解除阶段 0 的「未验证可用」标记。
5. **动态基线**：在 venv 中 `import` 原版 `backend.graph` 并 `compile()`，从**图对象**导出节点名、边、入口/终点，写进 baseline（比 grep 更可信）；记录原版依赖版本。
6. **如实标注**：没有 key，所以本轮**不产出真实检索报告、不产出耗时/成本数字**。原版 `/research` 的真实调用与 live baseline 剥离为任务 #13，挂到 S8，不能伪装完成。

### S1 实测结果（2026-11-14）

| 动作 | 结果 |
|---|---|
| 上游落地 | 143 个文件、`LICENSE` 完整、上游 commit `23fe92d` 与 remote `upstream` 可查、`.env.example` 冲突另存 `docs/upstream.env.example` |
| venv | Python 3.11.9 独立环境；官方 PyPI 源装齐 99 个包并导出 `requirements.lock.txt`；清华镜像不可用（已记录）。**S2 复查后改用 uv 重建**，见第 4 节 |
| YAML | 两份配置 `yaml.safe_load` 全量通过，阶段 0 欠账解除 |
| 图对象 | 真实 `compile()` 成功；**12 节点 / 14 边 / 0 条件边 / 无 checkpointer**，与静态核查一致 |
| 纯节点 | grounding / collector / curator 真跑成功；阈值 0.4 过滤行为与引用数可复现 |
| 新发现缺陷 | `typing.TypedDict` + Python 3.11 + pydantic 2.14 导致 `get_input_schema()` 抛 `PydanticUserError` → S2 改用 `typing_extensions.TypedDict` 并补 schema 用例 |

完整证据见 `docs/BASELINE.md` 与 `baseline/upstream_graph.json`。

---

## 4. S2 后复查与补账（2026-11-14，用户要求「先检查再进下一阶段」）

逐条对账 S0–S2 的承诺与仓库实况，发现 5 个缺口，全部已补：

| # | 缺口 | 影响 | 处理 |
|---|---|---|---|
| 1 | `.venv` 是 `python -m venv` 建的，不是 uv | 用户明确要求 uv 环境；依赖不可复现 | 新增 `pyproject.toml` / `.python-version` / `uv.lock`，`uv venv --python 3.11 --clear` 重建，`uv sync --frozen` 复跑幂等、`uv pip check` 103 包兼容 |
| 2 | 无 `pyproject.toml`，但 `langgraph.json` 写着 `dependencies: ["."]` | LangGraph Server 装不上项目 | pyproject 已可 build（`uv sync` 实测 Build 成功） |
| 3 | `langgraph` / sqlite saver / pytest / pyyaml 只靠手动 pip 安装 | 换机器 `pip install -r requirements.txt` 会缺依赖 | 全部写进 `pyproject.toml` 并锁进 `uv.lock` |
| 4 | `evals/fixtures/tavily_responses.json` 被 3 处引用却不存在 | S3 的回退/降级用例无数据可跑 | 补 `sufficient / sparse / empty` 三类合成样本 + `tests/test_fixtures.py` 5 个契约测试 |
| 5 | `ResearchState` 里 `retry_count` / `evidence_verdict` / `rewrite_queries` / `briefings` / `review_notes` 是裸 dict/list，且缺 `degraded` 字段 | S3 回退第二轮会整体覆盖第一轮状态，直接违背 AGENT.md 第 6.3 条 | 补 `merge_mapping` / `append_unique` / `append_notes` reducer、`degraded` + `degraded_sections` 字段，新增两轮写回回归测试 |

复查后 `uv run python -m pytest -q` → **16 passed**（原 10 + fixture 契约 5 + reducer 回归 1）。

当时仍未做、且不属于本阶段欠账的：S4 重建完整业务图后补端到端用例（`docs/BASELINE.md` 第 7 节已挂）——**该欠账已在 S3 复查时补齐**（`tests/test_checkpointer.py:84` 用真实 7 节点图做重启恢复，S4 换成子图后仍通过）；#13 真实 `/research` baseline 仍等 key。

---

## 3. 全局纪律（每一步都检查）

- 「跑通」= 真实执行代码并拿到输出；静态检查只能作为补充，不得冒充实测。
- 指标数字只能由 `evals/run_eval.py` 产出；未跑出的数字一律写 `X`。
- 每个技术结论都要能指到具体文件与行号 / commit。
- 每次完成一步：更新任务状态 → 写工作区记忆日志 → 再进入下一步。
- 遇到环境阻塞（缺 key、装不上包）如实记录，不静默降级、不编造结果。

---

## 5. S3 实测记录（2026-11-14）

新增 `capabilities/retrieval.py`（`@tool` 封装 fixture 数据源）、`graph/conditions.py`（纯函数三路路由）、`graph/nodes/{collect,decide,report}.py`、`graph/builder.py`（7 节点 + 条件边）、`graph/run.py`（CLI）、`tests/test_s3_loop.py`。

`uv run python -m graph.run --case <case> --trace` 三条真实运行轨迹：

| case | research 执行次数 | retry_count | verdict | degraded | 轨迹终点 |
|---|---|---|---|---|---|
| sufficient | 1 | `{}` | 4 栏目全 sufficient | false | `evidence_check → briefing` |
| sparse | 2 | `company=1` | 回退后 4 栏目全 sufficient | false | `evidence_check → rewrite_query → research → … → briefing` |
| empty | 3（= max_retry+1） | `company=2` | company=degraded，其余 sufficient | true | `… → degrade → briefing` |

- **精确回退**：sparse 第二轮 `research` 的 `sections` 只有 `["company"]`，没有唤醒其余 3 个栏目。
- **不编造**：empty 报告 Company Overview 输出「该类信息未找到公开依据」，`low-relevance` 无关 URL 出现 **0 次**；其余栏目仍正常输出。
- **引用同源**：正文 `[n]` 与末尾 References 由同一份 `state["references"]` 生成，CLI 报告可直接核对。
- **条件边真实存在**：编译后图对象里 `evidence_check` 为 conditional source，分支 3 条（测试断言）。
- **A/B 开关生效**：`features.self_correction=false` 时 sparse 直接 degrade，research 只跑 1 次。

`uv run python -m pytest -q` → **23 passed**（S2 及补账 16 + S3 7）。

**S3 如实边界**：仍为 fixture 模板简报，未接真实 LLM（S5）、未拆并行子图（S4）、未接 HITL（S6）；原版 `backend/prompts.py` 未改动但新图不加载它。`live` 检索在 `capabilities/retrieval.py` 中显式抛 `NotImplementedError`，留到 S5。

---

## 6. S3 后第二次复查与补账（2026-11-14 14:35）

对账范围经用户确认为 **S0–S3 全部已做阶段**。检查方式全部是真实执行：重跑 `pytest`、三档 CLI、`uv sync --frozen` / `uv pip check` / `baseline/inspect_upstream.py`，再逐条比文档承诺与代码实况。

### 6.1 复核通过

`23 passed → 33 passed`；`uv sync --frozen` 幂等、103 包兼容；基线复现仍是 12 节点 / 14 边 / 0 条件边；三档轨迹与第 5 节记录一致；工作区无 `.env` / `.db` / egg-info 被提交。复现基线脚本会刷新 `captured_at` 时间戳，已还原，工作区干净。

### 6.2 本轮补掉的 4 个真缺口

| # | 问题 | 代码位置 | 处理 |
|---|---|---|---|
| 1 | README 完全没有二次开发归因，违反 `AGENT.md` 第 2 条红线 | `README.md` | 顶部加归因声明、改动范围与当前真实状态（fixture 可跑 / 入口仍指原版 / 无任何指标数字） |
| 2 | A/B 开关命令行关不掉；`eval.yaml` 的 `ab_tests.overrides` 无解析器 | `config/settings.yaml` L56–62、`config/loader.py` | features 改 `${FEATURES_*:default}`；`.env.example` 补变量；新增纯函数 `apply_overrides()` 解析点号路径、非法路径抛错；测试断言 4 组 A/B 全部可应用 |
| 3 | 文档数 > `max_references` 时正文出现「有结论、无引用」 | `graph/nodes/report.py` | 正文与 References 共用同一份选中文档并统一编号；来源字典查不到的文档不进正文；超量截断写进 `review_notes`。实测 12 篇 → 10 条事实全带 `[n]`、0 条孤儿 |
| 4 | checkpoint 端到端用例仍用 1 节点最小验证图（`BASELINE.md` 第 7 节自挂欠账） | `tests/test_checkpointer.py` | 新增 `test_s3_business_graph_state_survives_restart`，用真实 7 节点图验证重启后 report / references / evidence_verdict / briefings / retry_count 全量恢复 |

实测：`FEATURES_SELF_CORRECTION=false uv run python -m graph.run --case sparse --trace` → `research_runs=1`、`degraded=true`（开关真生效）；三档 CLI 的 `report_chars` 仍是 822 / 829 / 561，无行为回归。

### 6.3 登记但不在本阶段动的边界（不假装已修）

> **历史快照**：本表是 S3 复查当时（S4 之前）的记录，「现状」列描述的是**当时**的代码，不是当前状态。入口接线、三个行为偏差已在 S4 / S5-B 解决，见 7.8 / 9.6 / 10.5 与 `BASELINE` 13–14；当前仍欠的只有内容级 `citation_traceability`（S7）。

| 项 | 现状（当时） | 归属 / 后续 |
|---|---|---|
| **对外入口仍跑原版图** | `langgraph_entry.py:4`、`application.py:115` 仍指向 `backend.graph.Graph`；新图只能靠 CLI 跑。规划里原本就没排「接线」这一步 | **S5-B 已切换**：两个入口都指向新图（见 9.6 / `BASELINE` 13） |
| `evidence_check` 只数篇数、不验内容 | `graph/nodes/decide.py:31–37` 判定是「每栏目合格文档 ≥ 2」；empty 报告里「该领域缺少公开规模数据」也带 `[n]` | S7 的 `citation_traceability`（来源确实支持 claim）需要 judge / golden set，S3 无实现手段 |
| `any(retry_count >= max_retry)` 整体降级 | `graph/conditions.py:45`：一个栏目达上限会连累其他栏目 | S4 拆子图时一并改成栏目级降级 |
| `degrade.enabled=false` 仍置 `degraded=True` | `graph/nodes/decide.py:78–97`，只影响措辞 | S4 明确该配置语义或删除 |
| `curated_data` 按 URL 累积 | `merge_docs` 无法移除上一轮已失效引用 | S4 配合子图重算 |
| `features.structured_output` / `human_review` | **历史快照（S3 复查当时）**：已可环境变量覆盖，但代码尚未消费 | 现已落地并验收：`structured_output` 见 9.6，`human_review` 见 10.5 |

---

## 7. S4 执行计划：并行子图 + 精确派发 + 还清 3 个行为偏差

> 制定：2026-11-14 15:00 | 依据：`docs/PROJECT_PLAN.md` 3.3/3.4、`AGENT.md` 第 6 条、下列前置实测

### 7.1 代码级现状（S3 结束时，逐行核过）

- `graph/builder.py:29-59`：主图 7 节点，`research` 是**单个节点**；`graph/nodes/collect.py:37-62` 一次性取回 4 个栏目结果，没有图级并行。
- `graph/conditions.py:26-29`：「精确回退」靠单节点内部 Python 过滤 `sections_to_research` 白名单实现，不是 LangGraph 编排。
- `graph/state.py:83,90`：`curated_data` / `references` 用 `merge_docs` 累积，第二轮无法移除已失效引用。
- `graph/conditions.py:45`：`any(...)` 让一个栏目达上限就连累其他栏目提前终止。
- `graph/nodes/decide.py:78-97`：`degrade.enabled` 只换措辞、仍置 `degraded=True`，配置名不副实。

### 7.2 前置技术探针（uv 环境 + AsyncSqliteSaver 临时库真跑，不是查文档猜的）

| 验证点 | 实测结果 |
|---|---|
| 编译后的子图能直接当主图节点 `add_node("research", compiled_sub)` | ✅ |
| 子图内 `Send` 按白名单派发到并行 worker，各写同一字段经 reducer 合并 | ✅ 输出 `['company','news']`，未互相覆盖 |
| 主图 `astream(stream_mode="updates")` 节点名仍是 `research` | ✅ 三档 CLI 的 `trace.count("research")` 不会破 |
| 附带发现 | `from langgraph.constants import Send` 已弃用告警，**必须**用 `from langgraph.types import Send`（LangGraph 1.2.22） |

### 7.3 设计决策

1. **主图节点名保持 `research`**，值由函数换成编译子图。S3 的三条轨迹、CLI `research_runs` 统计与 `tests/test_s3_loop.py` 断言都依赖该名字，改名收益不抵回归风险；白板上把 `research` 展开讲即可。
2. **子图用独立 `ResearchSubgraphState`**：只含 `company / sections_to_research / retry_count / active_section + 4 个 *_data + review_notes`。输出字段是 `ResearchState` 子集且同名 reducer（探针已验证可合并回主图），避免把内部派发字段污染主 State。
3. **精确派发用 `Send`**：`dispatch` 的条件边返回 `Send("analyst", {**state, "active_section": s})` 列表；首轮白名单为空 → 4 个 Send 全派发，回退轮只派发不足栏目。彻底替代 S3 的「单节点内 Python 过滤」。
4. **回退白名单写进 State**：新增 `ResearchState.sections_to_research`（`latest_list` reducer，last-write-wins），由 `rewrite_query` 写入，子图只读。
5. **三个偏差一起收**：
   - `any` → `all`，白名单排除已达上限栏目 → 各栏目用尽自己的重试额度才整体拒答，不再连累；
   - 删除 `degrade.enabled`（防幻觉是红线，不可关闭），`DegradeConfig` 只留 `message`；
   - `curated_data` / `references` 改用 `replace_mapping` reducer，curate 每轮全量重算。**如实范围**：只有「同一 URL 的新版本被判低分/无 URL」时旧引用才会消失；`*_data` 仍按 URL 累积，「URL 不再返回」的旧引用目前移除不掉（S4 复查实测，见第 7.8 节）。

### 7.4 任务与验收

| # | 动作 | 产出 | 验收标准 |
|---|---|---|---|
| 7.1 | 子图 State + dispatch/analyst + builder | `graph/subgraphs/` | 4 路 Send 并行、reducer 合并不覆盖、单测通过 |
| 7.2 | 主 State / 配置 / 主图接线 | `graph/state.py`、`builder.py`、`collect.py`、`decide.py`、`report.py`、`config/*` | 编译后主图仍 7 节点，`research` 是子图 |
| 7.3 | 三偏差修复 + 回归用例 | `conditions.py`、`tests/test_s4_subgraph.py` | 覆盖「部分栏目达上限」「引用全量重算」「配置无 enabled」 |
| 7.4 | 全量实测 | CLI 三档 + pytest | research 次数仍 1/2/3、report_chars 822/829/561 不回归、测试全过 |
| 7.5 | 文档与提交 | ACTION_PLAN / BASELINE / AGENT.md、commit | 白板图可画、Send 导入规范、commit 可 diff |

### 7.5 白板图（目标形态）

```text
主图（7 节点，可完整画出）
START → grounding → [research 子图] → curate → evidence_check
                          ↑               ├─ pass    → briefing → END
                          │               ├─ retry   → rewrite_query ─┘
                          │               └─ degrade → degrade → briefing → END

子图内部：START → dispatch ──Send──→ analyst(company)
                          ──Send──→ analyst(industry)
                          ──Send──→ analyst(financial)
                          ──Send──→ analyst(news)   → END
         回退轮按 sections_to_research 白名单，只派发不足栏目
```

### 7.6 边界（不谎称）

- 仍是 fixture 模板简报，不接真实 LLM / Tavily（S5）；对外入口仍指原版图（用户拍板 S5 再切）；内容级 `citation_traceability` 仍归 S7。【S4 历史快照：两个入口已在 S5-B 切到新图，见 9.6】
- **不写「主图从 11 节点收敛到 6～7」**：原版 11 节点图本项目并未重建，S3 起主图本来就是 7 节点。S4 的真实变化是「把 research 单节点换成 4 路 Send 并行子图，并让精确回退由图编排而非 Python 过滤实现」。

### 7.7 S4 实测结果（2026-11-14 15:10）

| 验收项 | 实测结果 |
|---|---|
| 主图 | 7 节点 `grounding / research / curate / evidence_check / rewrite_query / degrade / briefing`；`research` 是编译后的子图 |
| 子图 | START/END + `dispatch` + `analyst`，`dispatch` 挂真实条件边，用 `Send` 派发 |
| 首轮并行 | Notion 4 条 analyst 留痕（company/industry/financial/news），四类 `*_data` 全有文档且互不覆盖 |
| 精确回退 | Linear 首轮 4 个 Send、回退轮 **1 个 Send**（只 company）；`sections_to_research=["company"]` |
| 有上限循环 | empty 3 次 research（首轮 + 2 次回退），`degraded=true` |
| 三偏差 | `any→all`（部分栏目达上限仍 retry、白名单只剩有额度栏目）；`degrade.enabled` 已删；`curated_data`/`references` 改 `replace_mapping`，**同 URL 新版本不合格时**旧引用可移除（范围已按第 7.8 节复查收窄） |
| 回归 | `uv run python -m pytest -q` → **43 passed**；三档 `report_chars` 822/829/561、research 1/2/3、引用数 8/9/6，与 S3 完全一致 |
| A/B | `FEATURES_SELF_CORRECTION=false` → research 1 次、`degraded=true` |

**实测踩到并修掉的坑**：编译子图直接当主图节点时，若把主图已有的 `review_notes` 传进子图、又由子图输出带回，`append_notes` reducer 会把旧记录重复累加（sparse 首轮 4 条变 8 条）。修法：`StateGraph(..., input_schema=..., output_schema=...)` 隔离子图输入/输出，且 `Send` 只带编排参数、不带累积字段。另实测两个 API 事实：`Send` 必须从 `langgraph.types` 导入（`langgraph.constants` 在 1.2.22 已弃用）；`StateGraph` 的 `input`/`output` 参数也已弃用，应用 `input_schema`/`output_schema`。

**S4 如实边界**：仍是 fixture 模板简报；对外入口仍指原版图（S5 再切）；内容级 `citation_traceability` 仍归 S7。【S4 历史快照：S5-B 起入口已切换，见 9.6】

### 7.8 S4 复查修正（2026-11-14 15:40，用户要求逐条对账后补）

复查方式：`uv run python -m pytest -q`、三档 CLI 重跑、编译后 `get_graph()` 结构、临时探针（栏目级轮次 / 旧引用 / 并发耗时 / 子图嵌套 checkpointer 重启）。**验收表标 ✅ 标早了**，查出并修掉 2 个实质问题 + 3 处完成度不足：

| # | 问题 | 代码位置 / 证据 | 处理 |
|---|---|---|---|
| 1 | **栏目级重试下取错检索轮次（S4 新引入）** | `graph/subgraphs/research.py:73` 原为 `max(retry_count.values())`。构造 `company=2, industry=1` 实测 analyst 请求 `round_no=2`，应为 1；S3 全体一起回退时全局 max 没错，S4 改 per-section 后失效。三档 fixture 都只有 company 单栏目回退，所以没暴露 | 改为 `retry_count.get(section, 0)`；`decide.py` 留痕把单一 `round` 换成 `retry_rounds` 字典；新增端到端用例 `test_analyst_uses_its_own_retry_round_when_sections_are_out_of_sync`，并**反向验证**换回旧写法时该用例报 `captured=[('industry', 2)]` 失败 |
| 2 | **「旧引用可移除」措辞夸大 + 测试自我证明** | `*_data` 仍是 `merge_docs` 累积；实测第 1 轮 old URL、第 2 轮只新增 new URL，最终 references 仍含 old。原 `test_curate_recomputes_references_so_stale_urls_disappear` 手工传空 `company_data` 再手工调 reducer，绕开真实链路 | 拆成两条：一条走真实 `merge_docs → curate → replace_mapping` 链验证「同 URL 新版本被判低分」确能移除；一条如实断言「URL 不再返回时旧 URL 保留」并记录为已知边界（需按栏目维护有效 URL 集合，挂 S5/S7）。第 7.3/7.7、BASELINE 11 三处措辞同步收窄 |
| 3 | 并发性只有口头证据 | 临时探针：4 路 Send 耗时 **0.181s**（带 0.15s 延迟的工具，串行理论 0.600s），4 分支全执行、`*_data` 互不覆盖 | 新增 `test_send_branches_overlap_in_time`（时间窗重叠断言，不依赖绝对耗时），实测数字写入 BASELINE 11 |
| 4 | README 主体仍是原版 | Architecture 图还是 `analyzers → collector → curator → briefing → editor`；`Run locally` 教 `uv pip install -r requirements.txt`，与 `AGENT.md` 禁止直接 pip install 冲突 | 补「Upstream / This fork」双架构图 + 7 节点主图 + Send 子图白板图；运行指令改 `uv sync --frozen`；Prerequisites 注明 key 只属上游 app |
| 5 | 文档过期 | 第 2 节结尾仍写「S4 后补真图端到端用例」仍未做 | 改为「已于复查前补齐（`tests/test_checkpointer.py:84`）」 |

**复查补充实测**：编译后主图 `__start__/__end__` + 7 业务节点；子图 `dispatch` 挂真实条件边；子图嵌套下重开 `CheckpointSession`，report/references/evidence_verdict/retry_count/review_notes/degraded 六项全恢复。`46 passed`，三档 `report_chars` 822/829/561 零回归。

---

## 8. S5 执行计划：LangChain 深化（结构化输出 / 真实检索 / 入口切换）

> 制定：2026-11-14 16:00 | 依据：`PROJECT_PLAN.md` 5.1/5.2、`ACTION_PLAN` 主表 S5 行、下列前置实测
> 前置复查：S4 的 5 个补账项重新逐条核过，`46 passed`、三档零回归、工作区干净（`addea68`），无遗留问题。

### 8.1 代码级现状（S4 结束时，逐行核过）

- `graph/nodes/report.py:72-74`：简报正文是 `doc["content"]` 直接拼字符串，没有 LLM；`features.structured_output` 在 `graph/` / `capabilities/` 里**零引用**（只存在于 yaml 和 eval 的 A/B 配置）。
- `capabilities/retrieval.py:76-80`：`live` 模式显式抛 `NotImplementedError`；只有 `@tool` 封装的 fixture 数据源，没有 `BaseRetriever`。
- `config/settings.yaml:41-52`：`models` 已有 `temperature / max_retries / roles(4 角色) / fixture.stub`；`.env.example` 已列 OPENROUTER / OPENAI / GEMINI / TAVILY 四组 key。依赖 `langchain-openai==1.2.1`、`langchain-google-genai==3.0.3`、`tavily-python==0.7.24`、`httpx==0.28.1` 均已锁进 `uv.lock`。
- `backend/llm.py:21-27,47-85`：上游 `create_llm()` 直接 `os.getenv` 且硬编码模型名（`_OPENAI_MODELS` / `_GEMINI_BRIEFING_MODEL` / `DEFAULT_OPENROUTER_MODEL`），违反 `AGENT.md` 第 5、8 条 → **不复用**，保留为上游原样。
- `langgraph_entry.py:4` = `Graph().compile()`（原版线性 DAG）；`application.py:115-142` = 原版 `Graph(...)` + `graph.run(thread={})`，把每个 state dict 的第一个 key 当 `current_step` 写进 `job_status`，最终从 `final_state['report']` 取报告。
- `PROJECT_PLAN.md:170-190` 已给出 `Fact` / `SectionBrief` 契约草稿（本阶段落地为 `graph/contracts.py`）。

### 8.2 前置技术探针（uv 环境真跑，无 key、无网络，不是查文档猜的）

| 验证点 | 实测结果 |
|---|---|
| `convert_to_openai_tool(SectionBrief)` | ✅ 生成 tool spec，字段 `degraded / facts / section` |
| `ChatOpenAI.with_structured_output(SectionBrief, method="function_calling")` | ✅ 返回 `RunnableSequence`，绑定阶段不发请求 |
| **`httpx.MockTransport` 注入 `http_async_client` 后 `ainvoke`** | ✅ **无 key 真跑出 `SectionBrief` 实例**；请求体字段 `messages/model/tools/tool_choice/parallel_tool_calls/temperature/stream` |
| 模型返回缺 `source_url` 的非法对象 | ✅ 被 `ValidationError: facts.0.source_url Field required` 拦下，不是静默丢字段 |
| `GenericFakeChatModel.with_structured_output` | ❌ `NotImplementedError: with_structured_output is not implemented for this model` → **无 key 测试必须走 mock HTTP，不能用 LangChain 自带 fake model** |
| `BaseRetriever` 最小子类 `ainvoke` | ✅ 返回 `Document(page_content, metadata={url,...})` |
| 新图 `astream(stream_mode="updates")` | ✅ 5 个事件，格式 `{节点名: {字段: 值}}`，`list(ev.keys())[0]` 可直接喂 `application.py` 的 `current_step`；`aget_state` 取到 `report` 长 822 |
| 顶层 `build_graph(...).compile()` 不带 checkpointer | ✅ 9 节点（`__start__/__end__` + 7 业务）可编译，`astream` 可用；Studio 需由 Server 注入 saver |
| `AsyncSqliteSaver.from_conn_string` | ✅ 返回 `_AsyncGeneratorContextManager`（有 `__aenter__/__aexit__`），**不能**在模块顶层直接当 saver 对象使用 |
| 环境噪音 | `langchain-openai` 注入 transport 会打印代理告警，设 `LANGCHAIN_OPENAI_TCP_KEEPALIVE=0` 消除 |

### 8.3 设计决策

1. **key 分叉，不阻塞**：S5 拆「无 key 可实测」与「需 key」两轨。无 key 轨靠 `httpx.MockTransport` 注入真跑 `with_structured_output`、校验重试、URL 级回溯；**任何真实模型/Tavily 的准确率、延迟、成本数字一律不写**，live 实测仍归 S8。用户暂未提供 key，按无 key 轨推进，不空等。
2. **模型工厂配置驱动**：新建 `capabilities/llm.py` + `config/loader.resolve_llm_credentials()`。模型名只从 `settings.models.roles[role]` 读，温度/重试从 `settings.models`；provider 由凭据解析决定，禁止硬编码模型名、禁止业务代码直接 `os.getenv`。凭据**不进 `Settings`**（避免 `model_dump` 泄密钥），单独返回轻量对象。
3. **契约层与图解耦**：`graph/contracts.py` 定义 `Fact / SectionBrief / ResearchBrief`（`extra="forbid"`）；`capabilities/structured.py` 提供 LCEL 抽取链 `prompt | model.with_structured_output(...)`，校验失败最多重试 `models.max_retries` 次，仍失败 → 该栏目 `degraded=True` + `review_notes` 留痕，**禁止静默丢字段**。8.1 先在独立能力层测通，8.3 才接进 `briefing` 节点，避免一次改太多把三档跑坏。
4. **URL 级回溯，不冒充内容级**：`Fact.source_url` 必须出现在本次传入的文档 URL 集合里，否则剔除并写 `review_notes`。这只保证「引用指向真实检索到的来源」，**不等于** `citation_traceability`（来源确实支持 claim），后者仍需 judge/golden set，归 S7。
5. **Tavily 封 `BaseRetriever`**：`capabilities/tavily_retriever.py` 实现 `_aget_relevant_documents` 返回带 `url/title/score/section` 元数据的 `Document`；工具工厂按 `app.mode` 选 retriever 或 fixture tool。无 key 时用同接口 `FakeRetriever` 测编排，**不写「Tavily 实测」**。
6. **`features.structured_output` 真消费**：`briefing` 按开关选「结构化抽取 → 渲染」或「S4 模板」。开关关闭时行为与 S4 完全一致（`report_chars` 822/829/561 保持），作为 A/B 基线。
7. **入口切换放 8.4**：`langgraph_entry.py` 导出 `build_graph(...).compile()`（无 checkpointer，由 LangGraph Server 注入；需在 `AGENT.md` 第 6.7 条补这条例外并说明理由）；`application.py` 改用 `CheckpointSession` 编译新图 + `astream(updates)`，从 `aget_state` 取 report。切换后 `/research` 在 fixture 模式只返回合成报告，这是用户拍板「S5 再切」的既定代价，README 顶部已如实写明。
8. **不谎称**：live 代码路径在无 key 下只能静态检查 + mock，文档必须写「未做 live 实测」；不把 `httpx.MockTransport` 的结果说成真实模型结果。

### 8.4 任务与验收

| # | 动作 | 产出 | 验收标准 |
|---|---|---|---|
| 8.1 | Pydantic 契约 + 配置驱动模型工厂 + 结构化抽取器 + mock HTTP 测试 | `graph/contracts.py`、`capabilities/{llm,structured}.py`、`config/loader.py` 增凭据解析、`tests/test_s5_contracts.py` | 无 key 真跑 `with_structured_output`；缺 `source_url` 被拦；重试 1 次成功；重试耗尽降级留痕；URL 不在文档集合被剔除且留痕；角色模型名来自配置。**三档 CLI 零回归** |
| 8.2 | Tavily `BaseRetriever` + 工具工厂双模式 | `capabilities/{tavily_retriever,retrieval}.py`、`tests/test_s5_retriever.py` | fake retriever 走通编排；live 缺 key 明确报错不悄悄回退 fixture；fixture 三档不回归 |
| 8.3 | `briefing` 接入结构化输出 + 消费开关 | `graph/nodes/report.py`、`tests/test_s5_briefing.py` | 开关 on/off 都能跑；off 时报告与 S4 逐字一致；每条 Fact 对回 `references` 的 URL；降级栏目不编造 |
| 8.4 | 两个对外入口切到新图 | `langgraph_entry.py`、`application.py`、`AGENT.md` | Studio 图可编译；`/research` 的 `astream` 事件写 `job_status` 且能取到 report（fixture） |
| 8.5 | 全量实测、文档同步、提交 | `ACTION_PLAN` 8.6、`BASELINE` 12、`README`、commit | pytest 全过、三档 + A/B 回归、`uv pip check`、无 key 边界写清、工作区干净 |

### 8.5 S5 目标形态（白板图）

```text
能力层   capabilities/
           llm.py            配置驱动 ChatOpenAI / Gemini，模型名来自 settings.models.roles
           structured.py     ChatPromptTemplate | model.with_structured_output(SectionBrief)
           tavily_retriever.py  BaseRetriever → Document(url,title,score,section)
           retrieval.py      @tool 工厂：fixture / live 按 app.mode 选数据源
契约层   graph/contracts.py  Fact(claim, source_url, confidence) / SectionBrief / ResearchBrief
主图     ... → curate → evidence_check → briefing ── features.structured_output
                                          ├─ on  : 结构化抽取 + URL 回溯 + 渲染
                                          └─ off : S4 模板（A/B 基线，逐字不变）
入口     langgraph_entry.py / application.py  →  新图（S5 起）
```

### 8.6 边界（不谎称）

- 本阶段在**无 key** 环境下完成；`httpx.MockTransport` 只验证 LangChain 链路与契约，不代表任何真实模型能力。
- 真实 LLM / Tavily 调用、准确率、p95 延迟、单次成本、S8 真实实测**仍阻塞在 key**，不写任何数字。
- `citation_traceability`（来源内容确实支持结论）仍归 S7；S5 只做到 URL 级回溯。
- HITL（S6）、评测台（S7）、简历（S9）不因 S5 提前开工而顺延或假装完成。

### 8.7 S5.1 实测结果（2026-11-14 16:20，无 key / 完全离网）

**新增**：`graph/contracts.py`、`capabilities/llm.py`、`capabilities/structured.py`、`tests/test_s5_contracts.py`；`config/loader.py` 增 `LLMCredentials` / `MissingLLMCredentials` / `resolve_llm_credentials()`。

| 验收项 | 实测结果 |
|---|---|
| 结构化输出真跑 | `httpx.MockTransport` 注入 `ChatOpenAI(http_async_client=...)`，`prompt \| with_structured_output(SectionBrief)` 真发出 1 次调用，返回 `SectionBrief` 实例 |
| 缺 `source_url` | 被 `ValidationError` 拦下；重试 2 次仍失败 → 整栏 `degraded=True`、`facts=[]`、`review_notes` 两条 `validation_failed` + 一条 `degraded`，**没有静默丢字段** |
| 校验重试 | 第一次非法、第二次合法 → 成功，留痕 `["validation_failed", "ok"]` |
| URL 级回溯 | 模型编造文档外的 URL → Fact 被剔除、写 `dropped_uncited_facts` 留痕、整栏降级 |
| 空文档短路 | 不调用模型（`seen == []`），直接降级 |
| 配置驱动 | 把 `models.roles.briefing` 改成 `my/custom-model`，请求体 `model` 字段随之改变；温度同样来自配置 |
| 凭据安全 | OpenRouter 优先；`SecretStr` 使明文不出现在 `repr`；无 key 抛 `MissingLLMCredentials` 并提示 `APP_MODE=fixture`，**不自动回退** |
| 契约严格性 | `extra="forbid"` 拦下额外字段，`confidence>1` 被 `ValidationError` 拦下 |
| 全量回归 | `55 passed`（S4 的 46 + 新增 9）；三档 `report_chars` 822/829/561、research 1/2/3、引用 8/9/6 零变化；`FEATURES_SELF_CORRECTION=false` 仍生效；`uv pip check` 103 包兼容 |

**「完全离网」的硬保证**：测试里的 `CREDS.base_url` 指向不可达的 `http://127.0.0.1:1/v1`。MockTransport 拦截所有请求；一旦注入失效，请求会立刻 connection refused 而不是静默走外网。另实测 LangChain 自带 `GenericFakeChatModel` 抛 `NotImplementedError`，**不能**用来测 `with_structured_output`，这是选 mock HTTP 的原因。

**两个诚实边界**：① 首次构造 `ChatOpenAI` 约 6s 是 SDK 一次性初始化（后续调用 0.02s），不是网络等待；② 这些结果只证明 LangChain 链路与契约正确，**不代表任何真实模型能力**，准确率/延迟/成本一个数字都不写。live 实测仍阻塞在 key（S8）。

**S5 剩余**：8.2 Tavily `BaseRetriever` 与双模式工具工厂、8.3 `briefing` 接结构化输出并消费开关、8.4 两个入口切到新图、8.5 全量验证与文档收尾。

---

## 9. S5-B 执行计划：S5 剩余 8.2–8.5（含 Tavily 额度护栏）

> 制定：2026-11-14 16:36 | 前置：`3e57ebf`（S5.1 完成，55 passed，工作区干净）
> 用户约束：**`TAVILY_API_KEY` 已设在 Windows 用户变量，谨慎使用、不要把免费额度跑没了，非必要不调用**。

### 9.1 key 现状实测（只查存在性，不读取/打印明文，不发起任何 API 请求）

| 项 | 实测结果 | 影响 |
|---|---|---|
| `TAVILY_API_KEY` 用户级 | ✅ 存在（长度 54） | 可供 S8 真实实测使用 |
| `TAVILY_API_KEY` 当前进程 | ❌ 未继承 | 终端/IDE 需重启才能继承；**本阶段不需要它**，也不写进 `.env` |
| `OPENROUTER_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GEMINI_API_KEY` 用户级与进程级 | ❌ 全部未设置 | live LLM 链路仍不可实跑；8.3 用本地 mock 后端真跑 LCEL，不得写成真实模型结果 |

**结论**：本阶段真实 Tavily 调用次数目标 = **0**，真实模型调用次数 = **0**，并且要有代码级证据（预算计数器 + 测试断言），不能只靠「我没去调」。

### 9.2 额度护栏设计（写进代码，不靠约定）

1. **三重 opt-in**：`APP_MODE=live` + `TAVILY_LIVE_ENABLED=true` + `TAVILY_MAX_CALLS>0`，缺任一律抛 `LiveRetrievalDisabled`，**绝不悄悄回退 fixture**。默认值分别是 `fixture / false / 0`，即「装好 key 也调不动」。
2. **进程内硬预算**：`CallBudget` 计数，每次真实请求前 `consume()`，用尽抛 `TavilyBudgetExceeded`；暴露 `calls_made / cache_hits / remaining` 供测试与日志核对。
3. **先查缓存再扣额度**：`(query, params)` 的 sha256 落盘 `evals/cache/tavily/*.json`（加入 `.gitignore`）。命中缓存直接返回 `Document`，**不消耗额度**；S8 真调一次后可反复离线复现。
4. **dry-run**：`TAVILY_DRY_RUN=true` 只记录「将要发出的 query」并返回空结果，0 次真实请求。
5. **key 只由环境变量解析**：`config.loader.resolve_tavily_credentials()` 用 `SecretStr`、不进 `Settings`、不写日志、不接收请求体里的 `tavily_api_key`。`/research` 请求体的 key 字段在新图中**明确不消费**（上游遗留字段，文档写清）。
6. **测试永不用真 client**：注入 fake client / fake retriever；加一条断言 `AsyncTavilyClient` 在 fixture 与测试里从未被实例化。

### 9.3 任务与验收

| # | 动作 | 产出 | 验收标准 |
|---|---|---|---|
| 8.2 | `TavilyRetriever(BaseRetriever)` + 预算/缓存/dry-run + 工具工厂双模式 | `capabilities/tavily_retriever.py`、`capabilities/retrieval.py`、`config/{loader,settings}.yaml`、`.env.example`、`tests/test_s5_retriever.py` | 默认配置下真实 client 0 次构造；`max_calls=0` 抛错；`=1` 时第 2 次抛 `TavilyBudgetExceeded`；缓存命中不扣额度；dry-run 0 次请求；fixture 三档零回归 |
| 8.3 | `briefing` 接结构化输出 + 消费 `features.structured_output` | `capabilities/briefing.py`、`graph/nodes/report.py`、`tests/test_s5_briefing.py` | on 走真 LCEL（fixture 用本地 mock 后端，逐栏目留痕 `structured_extract`）；off 与 S4 报告**逐字一致**（822/829/561）；每条 Fact 的 `source_url` 落在 `references`；降级栏目不编造 |
| 8.4 | 两个对外入口切到新图 | `langgraph_entry.py`、`application.py`、`AGENT.md` 6.7 例外、`tests/test_s5_entrypoints.py` | 顶层 `graph` 可编译且不带 checkpointer（Server 注入）；`process_research` 用 `CheckpointSession` + `astream(updates)` 写 `job_status`、从 `aget_state` 取到 report（fixture 822 字符）；全程 0 次外部调用 |
| 8.5 | 全量实测、文档同步、提交 | `ACTION_PLAN` 9.6、`BASELINE` 13、`README`、`AGENT.md`、`commit`、工作区日志 | pytest 全过、三档 + A/B 回归、`uv pip check`、Tavily/模型真实调用计数 = 0 有据可查、工作区干净 |

### 9.4 技术决策（避免上一轮那种「标 ✅ 标早了」）

1. **fixture 也真跑 LCEL**：`briefing` 的结构化分支在 fixture 模式用 `httpx.MockTransport` 注入 `ChatOpenAI`，handler 从 prompt 的 `<documents>` 里把每篇文档确定性转成 `Fact(claim=content, source_url=url, confidence=score)`。这样 `prompt | with_structured_output` 是**真实执行**的，但它是确定性 stub 而非模型能力，文档必须写死这条边界。
2. **on/off 报告逐字一致是设计目标**：因 stub 的 claim 就是 `doc["content"]`，两条路径渲染结果相同；用 `review_notes` 的 `structured_extract` 留痕 + mock 请求计数证明 on 分支确实走了链路，而不是靠报告差异。
3. **不在节点内 `asyncio.gather`**：4 个栏目抽取在 `briefing` 内串行 loop（mock 单次 ~0.02s），符合 `AGENT.md` 6.4；不新增子图、不动 S4 的主图结构。
4. **`initial_state(company)` 之外的上游入参不伪装支持**：`company_url / industry / hq_location / model / 请求体 key` 新图不消费，README 与文档如实写明；`thread_id` 在模板基础上追加 `job_id` 保证并发隔离。
5. **入口切换不碰 `/config`、`/stream`、PDF 等上游端点**，只替换 `process_research` 的图与 `langgraph_entry.py` 的导出，缩小改动面。

### 9.5 边界（不谎称）

- 本阶段**不发起任何真实 Tavily / 模型调用**；不计任何准确率、延迟、成本数字；live 实测与真实指标仍归 S8，需用户明确放行额度后才执行。
- fixture 的结构化输出是确定性 stub，**不代表真实模型能力**；`citation_traceability` 内容级判定仍归 S7。
- S6 HITL、S7 评测台、S9 简历不提前开工、不假装完成。【S5 历史快照：S6 见第 10 节、S7 见第 11 节，均已于本日完成】

### 9.6 S5-B 实测结果（2026-11-14，0 次真实 Tavily / 模型调用）

**新增**：`capabilities/{tavily_retriever,briefing}.py`、`tests/test_s5_{retriever,briefing,entrypoints,offline}.py`；改造 `capabilities/{retrieval,llm}.py`、`graph/nodes/report.py`、`config/{loader,settings}.yaml`、`.env.example`、`langgraph_entry.py`、`application.py`、`README.md`、`.gitignore`。

| 验收项 | 实测结果 |
|---|---|
| 额度护栏 | 默认 `APP_MODE=fixture / live.enabled=false / max_calls=0`；三重 opt-in 缺一即抛 `LiveRetrievalDisabled`；缺 key 抛 `MissingTavilyCredentials`，**不回退 fixture** |
| 硬预算 | `max_calls=1` 时第 2 次不同 query 抛 `TavilyBudgetExceeded`，fake client 只收到 1 次；缓存命中 `calls_made` 不增且不会凭空多出额度；dry-run 返回空且 client 0 次调用 |
| **0 次真实调用的硬证据** | `tests/test_s5_offline.py` 把 `socket.connect` 换成守卫（只放行本地回环，Windows asyncio self-pipe 需要），完整跑一次图仍产出 822 字符报告，被拦截的外部连接次数 = **0**；另有 reload Studio 入口 + 替换 `AsyncTavilyClient` 为抛错哨兵的用例 |
| 结构化输出双路径 | on 真跑 `prompt \| with_structured_output(SectionBrief)`，三档留痕 4/4/3 条 `structured_extract`；off 与 S4 报告**逐字一致**；12 篇文档截断时 10 条结论全部带 `[n]` |
| URL 级回溯 | 注入编造 URL 的 `SectionBrief` → `dropped_uncited_facts` + 整栏拒答，报告不含编造内容；后台 `degraded=True` 同样拒答 |
| 入口切换 | Studio 顶层 `graph` 编译后含 7 个业务节点、`checkpointer=None`（Server 注入）；`process_research` 用 `CheckpointSession` + `astream(updates)` 完成，`current_step` 落在业务节点；**真发 POST `/research`** 端到端完成且报告 822 字符；请求体 key 未被消费/外泄 |
| 全量回归 | `85 passed`；三档 `822/829/561`、research 1/2/3、引用 8/9/6 与 S4 完全一致；`FEATURES_SELF_CORRECTION=false` 与 `FEATURES_STRUCTURED_OUTPUT=false` 均生效；`uv pip check` 103 包兼容 |

**踩到并修掉的两个真问题**：① `httpx.MockTransport` 的 handler 里把 human 消息按 `role == "human"` 找，但 OpenAI 请求体里是 `role == "user"`，导致 payload 为空、四栏全部误判降级；改为从 `user`/`human` 取并兼容多模态 part list，补了回归用例。② `make_briefing_node` 初版用模块级全局 `_index` 传引用编号，并发下会串号；改为显式传参。另给注入 client 的 `ChatOpenAI` 加 `http_socket_options=()`，消除 SDK 的代理告警。

**如实边界**：`AsyncTavilyClient.search()` 的 live 行为**未实测**（0 次真实请求）；fixture 结构化输出是确定性 stub，不代表模型能力；`citation_traceability` 内容级判定仍归 S7；真实准确率/延迟/成本仍归 S8，需用户明确放行额度。

### 9.7 S5-B 复查补账（用户拍板「全部补掉再进 S6」）

复查方式：重跑 `85 passed` / `uv sync --frozen` / 逐行核代码 / 4 组真跑探针，不凭上一轮印象。主体（护栏、结构化双路径、入口、README 归因）确实干得好，但验收表标 ✅ 标早了。

| 查出的问题 | 性质 | 修复 |
|---|---|---|
| `httpx.AsyncClient` 泄漏 | **真 bug**：实测 5 次 `run_research` 创建 5 个、未关闭 5 个；`aclose()` 只在 `test_s5_briefing.py:172` 调过，CLI / `/research` / Studio 全没关。长驻服务每请求泄漏一个 | 新增 `briefing_backend_scope()`（`finally` 关闭）+ `build_graph(..., briefing_backend=...)` 注入；CLI / `/research` 走 scope，Studio 模块级单例只建一次（reload 复用，不重复创建） |
| `confidence=score` 承诺没落地 | 9.4 白纸黑字写 score，代码硬编码 `0.9`，`_format_payload` 也没把 score 放进 prompt；实测 `score=0.41` → 返回 `0.9` | `_format_payload` 带 score，`_score_as_confidence()` 夹到 `[0,1]`，缺失/非法记 0.0 |
| `/research` 零外部调用只靠推断 | 证据不齐：`test_s5_offline.py` 只守 CLI 路径 | 补真发 POST + socket 守卫用例，实测 `completed` / 822 字符 / 拦截 **0** 次 |
| 三条边界没写清 | 完成度 | 见下 |

**新增测试**：`tests/test_s5_lifecycle.py`（3 条：生产路径 0 泄漏、异常路径也关、confidence=score）、`test_s5_offline.py` 追加 1 条。**反向验证**：临时换回旧写法时 3 条 lifecycle 用例全失败，还原后通过，证明不是摆设。

**补写的四条边界**：

1. 上游 `GET /models` / `GET /config` 未改动（遵守 9.4「不碰上游端点」）；`/models` 会向 OpenRouter 发请求，**不属于**本项目的额度护栏与「0 次外部调用」结论。按用户拍板只补文档。
2. `APP_MODE=live` 且无模型 key → `build_graph()` **构造期**抛 `MissingLLMCredentials`，连 `LiveRetrievalDisabled` 都到不了；只放行真实检索需同时 `FEATURES_STRUCTURED_OUTPUT=false`。
3. `TAVILY_MAX_CALLS` 是 **per-run**：`/research` 每请求独立 `CallBudget`，Studio 是进程级单例；真实次数以 `calls_made` 为准。
4. 额外排雷：静态核对 `AsyncTavilyClient.search` 真实签名，`query/max_results/search_depth/topic` 均存在，`topic` 允许 `general/news/finance`、`search_depth` 允许 `advanced`，S8 不会因参数名白花额度。**这是读本地 SDK 签名，不是 API 调用**。

**验收**：`89 passed`；三档 822/829/561、两个 A/B 开关零回归；client 探针 5 次运行 0 个未关闭；`uv pip check` 103 包兼容。**真实 Tavily / 模型调用仍为 0**。

---

## 10. S6 执行计划：HITL 人工复核（图内 `interrupt` + CLI resume）

> 制定：2026-11-14 | 前置：`867da1d`（S5-B 复查补账完成，`89 passed`，工作区干净）
> 用户拍板：交互形态 = **图内 `interrupt()` + CLI 两步式 resume**；不动上游 SSE、不加 API resume 端点。

### 10.1 前置探针实测（真跑，不查文档猜）

| 探针 | 结果 |
|---|---|
| `interrupt` / `Command` 导入 | 均在 `langgraph.types`；`Command(resume=...)` 参数存在 |
| 首轮 `astream(updates)` | 产出 `['before', '__interrupt__']`；`aget_state().next == ('review',)`；payload 可从 `snapshot.tasks[].interrupts[].value` 取 |
| **跨 session 恢复** | 关闭 `CheckpointSession`、重开一个指向同一 SQLite 文件，用 `Command(resume={...})` 成功续跑，恢复后 `next == ()` |
| 现有断言约束 | `tests/test_s4_subgraph.py:97` **精确断言主图 7 节点集合** → 默认配置绝不能新增节点 |

### 10.2 设计决策

1. **默认零行为变化**：`FEATURES_HUMAN_REVIEW` 默认改为 `false`。开关关时 `build_graph` 不注册 `human_review`，条件边仍是 `pass→briefing` / `degrade→briefing`，主图严格 7 节点，三档 CLI 的报告与轨迹逐字不变。
2. **开关开时图结构**：`evidence_check` 的 `pass` 与 `degrade` 都先经过 `human_review` 再到 `briefing`（主图 8 节点）。`retry` 分支不变。
3. **两级开关**：`human_review=true` + `auto_approve_review=true` → 节点存在但**不调用** `interrupt()`，写 `auto_approved` 留痕（A/B 基线用）；`auto_approve_review=false` → 真 `interrupt()` 暂停。
4. **resume 决策契约**（受控 dict，不是自由文本）：`{"approved": bool, "rejected_sections": [str], "note": str}`。
   - `approved=true` → 原样出稿；
   - `approved=false` → 全栏目拒答；
   - `rejected_sections` → 只把这些栏目追加进 `degraded_sections`（`append_unique` reducer），并置 `degraded=True`。
   **人工决定必须能改变最终报告**，不能只是留个痕迹。
5. **不编造红线**：人工拒答复用 `degrade.message`「该类信息未找到公开依据」，不生成新文案、不留无引用结论。
6. **跨进程恢复**：CLI 第一次跑到中断即结束进程（打印 `thread_id` + interrupt payload），第二次 `--resume` 重开 `CheckpointSession` 指向同一 db 续跑；这比同一进程内 `input()` 更能证明 S2 的 checkpointer 不是摆设。
7. **0 外部调用**：全程 fixture；`briefing_backend_scope` 两次运行各建各关；禁网守卫继续生效。

### 10.3 任务与验收

| # | 动作 | 产出 | 验收标准 |
|---|---|---|---|
| 10.1 | State 契约 + `human_review` 节点 + 条件边接线 | `graph/state.py`、`graph/nodes/human_review.py`、`graph/builder.py`、`config/{settings.yaml,.env.example}` | 默认 7 节点、三档零回归；开关开时 8 节点且 `pass/degrade` 都经过复核 |
| 10.2 | CLI 两步式 resume | `graph/run.py` | `--review` 打印 thread_id 与 interrupt payload；`--resume --decision approve/reject` 能在**新进程**续跑出报告 |
| 10.3 | 验收测试 | `tests/test_s6_hitl.py` | 默认零回归、auto 不中断、真 interrupt 暂停、跨 session 恢复、拒绝后报告改变且不编造、开关关闭时无节点 |
| 10.4 | 全量实测、文档同步、提交 | `ACTION_PLAN` 10.5、`BASELINE` 14、`README`、`AGENT.md`、commit、工作区日志 | pytest 全过、三档 + A/B 零回归、`uv pip check`、真实调用 0 次、工作区干净 |

### 10.4 边界（不谎称）

- 只做 CLI resume；**不提供 API/SSE 复核端点**，上游流式逻辑一行不动（用户拍板）。
- 人工复核没有前端界面，payload 与 decision 都是 JSON；这不是「产品化 HITL」，是**可验证的图编排能力**。
- `auto_approve_review=true` 是无人值守默认值，避免 `/research` 永久卡在中断；真实复核需显式关掉它。
- 全程 fixture、0 次真实 Tavily / 模型调用；S7 评测台、S8 真实实测、S9 简历不提前开工。【S6 历史快照：S7 已完成，见第 11 节；S8/S9 仍未开工】

### 10.5 S6 实测结果（2026-11-14，0 次真实 Tavily / 模型调用）

**新增**：`graph/nodes/human_review.py`、`tests/test_s6_hitl.py`；改造 `graph/{state,builder,run}.py`、`config/settings.yaml`、`.env.example`。

| 验收项 | 实测结果 |
|---|---|
| 默认零回归 | `FEATURES_HUMAN_REVIEW=false` → 主图严格 7 节点、无中断；三档 822/829/561、research 1/2/3、引用 8/9/6 与 S5 一致 |
| 两级开关 | 开 `human_review` 后主图 8 节点；`auto_approve=true` 不中断且写 `auto_approved` 留痕；`auto_approve=false` 真 `interrupt()` |
| **跨进程恢复** | CLI 两个独立进程实测：第一步打印 `thread_id` / interrupt payload；第二步 `node_trace` 只有 `["human_review", "briefing"]`（前半段从磁盘恢复、未重跑），报告 829 字符与基线一致 |
| 人工决定能改报告 | `reject-sections news` → 只有 News 段输出「该类信息未找到公开依据」，其余栏目照常出稿；`reject` → 四栏全拒答、References 为空、无合成事实残留 |
| fail-safe | 非法 resume 值按「不批准」处理并整份拒答；未知栏目被白名单过滤且去重 |
| 0 外部调用 | `test_s6_hitl.py` 守卫 `socket.connect`（只放行回环），复核 + 恢复全程被拦截外部连接 = **0** |
| 全量回归 | `97 passed`；两个 A/B 开关生效；`uv pip check` 103 包兼容 |

**CLI 用法**（两次运行必须用同一 `--db` 与同一公司）：

```bash
uv run python -m graph.run --case sparse --review --db ./data/review.db
uv run python -m graph.run --resume --case sparse --db ./data/review.db \
  --decision reject-sections --reject-sections news --note "新闻来源存疑" --show-report
```

**如实边界**：只做 CLI resume，**没有** API/SSE 复核端点（用户拍板）；payload 与 decision 都是 JSON，不是产品化前端 HITL；`data/` 与 `*.db` 已在 `.gitignore`。【S6 历史快照】S7 已于本日完成（见第 11 节），S8/S9 仍未开工。

---

## 11. S7 评测台（2026-11-14，全程 fixture、0 次真实外部调用）

### 11.1 先纠正一个计划偏差：不编造 golden set

原表与 `PROJECT_PLAN.md` 7.1 写的是「30–50 家真实公司 × 每家 5 条可核验事实」。执行前复核发现这条在当前条件下**不能照做**：

1. `evals/fixtures/tavily_responses.json` 首行是项目自己写下的铁律：「合成样本……**禁止当作评测指标或事实来源**，真实指标只在 `APP_MODE=live` 下由 `evals/run_eval.py` 产出」；
2. 当前没有模型 key，也没有真实检索语料，用户明确要求「谨慎使用 Tavily 免费额度，非必要不调用」；
3. 于是硬写 50 家公司的 CEO / 融资轮次 / 成立年份，本质就是**编造标注**。拿编造的答案算出「准确率 95%」写进简历，面试一追问来源就穿，与本项目全程「不谎称」的取舍直接冲突。

**改法**：golden 由 `evals/build_golden.py` 从 fixture 语料 + `config/settings.yaml` 的 evidence 阈值规则**自动派生**（独立重算合格文档、回退轮数、应拒答栏目，不 import 任何图节点、不读被测系统输出），全部条目标注 `provenance: synthetic-fixture-derived`。它回答的是「给定这批语料，系统应当产出什么」，即**契约回归测试**，不是模型能力评测。`config/eval.yaml` 的 `min_companies` 由 30 改为 3 并写明原因；S8 拿到真实语料 / 人工核验标注后，只要换掉 `EVAL_DATASET_PATH`，`run_eval.py` 一行不用改。

这不削弱 S7 的工程验收（一条命令出分、能定位退化用例、数字可复现），但**S7 的分数不能当真实效果写进简历**——M4 简历数字必须来自 S8。

### 11.2 交付物

| 文件 | 职责 |
|---|---|
| `evals/build_golden.py` | 从 fixture + settings 派生 golden；`--check` 供 CI 校验同步（改了 fixture/阈值却没重生成就失败） |
| `evals/golden.jsonl` | 28 行 = 1 meta + 3 case + 23 claim + 1 abstain；每条 claim 自带 `source_content`，评测器自包含 |
| `evals/config.py` | `config/eval.yaml` 的 Pydantic 强类型校验（`extra="forbid"`），A/B 字段写错当场失败而不是静默出分 |
| `evals/metrics.py` | 报告解析、8 项指标、阈值门禁、A/B 有效性判定、回归比对（纯函数，可单测） |
| `evals/run_eval.py` | 编排 6 组 A/B × 3 case（18 次完整图运行）、写 `evals/scorecard.json`、CLI 与退出码 |
| `evals/scorecard.json` | 提交的基线分数，含用例级 `claim_records` / `failures`，可定位到具体结论 |
| `.github/workflows/eval.yml` | golden 同步 → 全量 pytest → 评测 + 回归门禁 → 上传 scorecard |
| `tests/test_s7_eval.py` | 24 例，含反向证伪、复查补账回归与额度护栏 |

**额度护栏**（对用户「不要把免费额度用没了」的硬落实）：`run_eval.py` 只在 `APP_MODE=fixture` 下启动，`live` 直接抛 `RuntimeError`；运行期间给 `socket.connect` 装守卫，非回环连接立即抛错，且一旦拦到连接就**作废本次结果**。所以即使配置被误改，本脚本也**不可能**消耗 Tavily / 模型额度。实测 `blocked_connection_attempts=0`、`tavily=0`、`llm=0`。

### 11.3 指标口径（fixture 下的准确定义）

| 指标 | 定义 | 边界 |
|---|---|---|
| `fact_accuracy` | 报告中同栏目出现 golden `expected_text` 的条数 / 23（**只管内容召回**） | 相对给定语料的召回，不是真实事实正确率；引用对错由 traceability 独立判定 |
| `citation_traceability` | 非拒答结论中「报告自带 `[n]` 且能映射回本次 References 的 URL，且 claim 文本归一化后出现在该 URL 的来源正文里」的占比 | **词法包含代理**，能抓拼错 URL / 张冠李戴 / 凭空造句 / 引用整段缺失，**不等价语义蕴含**；真实 judge 归 S8 |
| `abstain_rate` | 应拒答栏目真正输出拒答话术、无结论、且 `degraded_sections` 含该栏目的比例 | 1 条样本 |
| `hallucination_rate` | `1 - citation_traceability` | **互补指标，不是独立证据**，避免把同一数字当成两次验证 |
| `self_correction_success` | 首轮 insufficient、回退后转 sufficient 的比例 | 分母 1（sparse），其余 case 不计入 |
| `avg_retry_rounds` | 各 case `max(retry_count.values())` 均值 | 由 State 直接读，非估算 |
| `p95_latency_ms` | 本机墙钟 | 列为 `non_deterministic_metrics`，**不参与** CI 比对与 A/B 判定 |
| `cost_per_report` | fixture 下恒为 `0.0` | 0 次真实调用，**不是真实单次成本** |

> **复查 P1 修正**：初版 `fact_accuracy` 也要求 `source_url` 匹配，而 `parse_report` 在没有 `[n]` 时会从 golden 按文本**反推** URL——等于用标准答案给报告补引用，导致关掉行内引用后 8 条无引用结论仍拿 `traceability=1.0`。现在反推的 URL 只作诊断（`url_inferred=True`），一律判 `no_explicit_citation`；两个指标拆开：内容归 `fact_accuracy`，引用归 `citation_traceability`。

scorecard 不写时间戳；`inputs_sha256` 锁定 settings / eval / **实际使用的** eval 配置 / golden / fixture 四份数据，`code_sha256` 单独锁定 `graph/`、`capabilities/`、`persistence/`、`config/loader.py` 与 `evals/*.py`。两者分开后，分数变动才能区分「输入变了」还是「代码变了」（复查 P2/P6）。

### 11.4 实测结果

| 组 | fact_accuracy | traceability | abstain | hallucination | self_correction | avg_retry | 判定 |
|---|---|---|---|---|---|---|---|
| **baseline** | **1.000** | **1.000** | **1.000** | **0.000** | **1.0** | **1.000** | gate PASS |
| `self_correction_off` | 0.870 | 1.000 | 1.000 | 0.000 | 0.0 | 0.000 | **changed** |
| `fewer_results` | 1.000 | 1.000 | 1.000 | 0.000 | 1.0 | 1.000 | no_effect |
| `free_text_output` | 1.000 | 1.000 | 1.000 | 0.000 | 1.0 | 1.000 | no_effect |
| `no_inline_citations` | 1.000 | **0.000** | 1.000 | **1.000** | 1.0 | 1.000 | **changed（负向对照）** |
| `no_human_review` | 1.000 | 1.000 | 1.000 | 0.000 | 1.0 | 1.000 | no_effect |

关掉自纠正后 `fact_accuracy` 掉 `0.130435`（23 条里丢 3 条），`self_correction_success` 1→0，退化用例被精确定位为 `sparse:company:0/1/2`（Linear 公司栏首轮只有 1 篇，不再回退就直接拒答）。`no_inline_citations` 是**故意关掉行内引用**的负向对照：内容仍全对，但 23 条结论全部没有可核验来源，`traceability` 1→0、`hallucination_rate` 0→1，8 条（sufficient 档）记为 `no_explicit_citation`。这两组是仅有的真实 `changed`，都可解释、可复现。

### 11.5 为什么如实标出 3 组 no_effect

- `fewer_results`（`retrieval.max_results_per_query=1`）：`capabilities/retrieval.py:make_document_tool` 的 fixture 分支直接 `store.fetch(...)`，**根本不读这个参数**；它只在 live 的 `TavilyRetriever` 里生效（S8）。
- `free_text_output`：S5 已实测结构化输出 on/off 报告**逐字一致**，所以内容指标必然相同。它证明的是「接入 LCEL 没改变可见报告」，不是「结构化输出没价值」。
- `no_human_review`：`features.human_review` 默认就是 `false`，override 与默认值同值；这组要在 `AUTO_APPROVE_REVIEW=false` 的复核场景才有对照意义。

评测台用 `compute_ab_effect()` 只比确定性指标向量：完全一致就标 `no_effect` 并写明原因，**不编造 delta**。这比「每组开关都有提升」更经得起追问。`no_inline_citations` 是复查 P1 后新增的常设防线：以后谁把行内引用改坏了，scorecard 里会立刻出现 `changed`，而不是悄悄拿满分。

### 11.6 CI 门禁与可复现

```bash
uv run python -m evals.build_golden --check          # golden 与 fixture/settings 同步
uv run pytest -q                                     # 全量回归
uv run python -m evals.run_eval                      # 一条命令出分并更新基线
uv run python -m evals.run_eval --compare evals/scorecard.json --output evals/scorecard.next.json
```

CI 对 `protected_metrics`（fact_accuracy / citation_traceability / abstain_rate / hallucination_rate）按 `regression_tolerance=0.02` 与方向（higher/lower）比对上一版的 **baseline**；用例级比对则覆盖**两版共同存在的所有 A/B 组**（复查 P4，否则 A/B 组退化会静默漏检），id 形如 `fewer_results:sufficient:company:2`。超容差或出现「上一版通过、本版失败」的 golden item 即失败并打印 `degraded_case_ids`。阈值只对 baseline 生效（A/B 组本就是"关掉能力"的对照）。

### 11.7 反向验证：指标不是恒满分

`tests/test_s7_eval.py` 里专门做了证伪，否则 1.0 毫无说服力：

- 把一条有据结论改成「Notion 已于 2026 年完成 IPO，市值 1 万亿」但保留 `[n]` → `content_mismatch` 被抓，`fact_accuracy` / `traceability` 下降、`hallucination_rate` 上升；
- 关掉行内引用 → 8 条无 `[n]` 结论全部判 `no_explicit_citation`，`traceability=0.0` 而 `fact_accuracy` 仍 1.0（P1 常设回归）；
- 本应拒答的 company 栏硬塞一条无来源结论 → `empty:company:abstain` 判失败；
- 构造 fixture 轮数不足的 case，断言 golden 模拟跑到 `max_retry+1` 轮；构造 A/B 组新增失败，断言回归门禁点名该组；
- `APP_MODE=live` 启动被拒、golden 样本不足拒绝出分、未知 A/B 组名报错、`--baseline-only/--ab` 互斥、非回环连接被守卫拦截并正确还原、两条独立评测的确定性部分逐字一致。

### 11.8 S7 如实边界（不谎称）

1. **这是契约回归，不是能力评测**：golden 与被测系统读同一份 fixture，baseline 满分是「系统把给定文档按规范搬进报告并加对引用」的必然结果，**不能写成「准确率 100%」**。
2. `citation_traceability` 是词法包含代理，不是语义蕴含 judge；真实判定需 S8 的模型/人工核验。
3. 只有 3 个场景原型、23 条 claim、1 条拒答；真实 30–50 家 × 5 事实的 golden 仍未做。
4. `cost_per_report=0`、`p95_latency_ms` 是本机耗时，均非真实成本/延迟；真实数字归 S8。
5. `no_inline_citations` 组的 `hallucination_rate=1.0` 是**故意关掉引用**的负向对照，不代表默认配置有问题，也不该被当成系统幻觉率。
6. S6 的复核留痕尚未导出为评测标注；没有 API/SSE 复核端点。
7. S8（真实实测，需模型 key + 用户明确放行 Tavily 额度）、S9（简历）仍未开工。

### 11.9 用法速查

```bash
uv run python -m evals.run_eval                       # 全量 6 组，写 evals/scorecard.json
uv run python -m evals.run_eval --baseline-only       # 快速自检
uv run python -m evals.run_eval --ab self_correction_off
uv run python -m evals.build_golden --check           # CI 同步校验
```

### 11.10 S7 复查补账（2026-11-14 18:56，用户要求「先检查上一步」）

按既有流程用**真实探针**复查，不是静态看代码。坐实并修掉 8 项：

| # | 问题（探针证据） | 修复 |
|---|---|---|
| **P1** | `FEATURES_INLINE_CITATIONS=false` 时报告 8 条结论全无 `[n]`，初版仍给 `traceability=1.0 / hallucination=0`——`parse_report` 从 golden 反推 URL，等于用标准答案补引用 | 反推 URL 标 `url_inferred` 并判 `no_explicit_citation`；`fact_accuracy` 改为只管内容召回，与引用指标解耦；新增 `no_inline_citations` 负向 A/B 组 + 单测 |
| P2 | `inputs_sha256` 只覆盖 4 份数据文件，文档却称能区分「代码变了」 | 新增 `code_sha256`（graph/capabilities/persistence/config.loader/evals 全部 `.py`，按 posix 相对路径排序保证跨平台一致） |
| P3 | fixture 轮数 < `max_retry+1` 时 golden 模拟提前降级（探针：算出 1 轮，真实图会跑 3 轮） | `_simulate_case` 只看重试额度，轮数用尽按空结果继续空转；补单测 |
| P4 | 回归比对只看 baseline，A/B 组新增失败用例 `passed=True` | 用例级比对扩展到两版共同的所有组，id 带组名；补单测 |
| P5 | `dataset.min_companies` 未校验，golden 空集 / 无拒答样本也会出满分门禁 | `build_scorecard` 前置校验，样本不足直接抛错拒绝出分 |
| P6 | `--config` 指向自定义配置时，指纹仍读默认 `eval.yaml` | `inputs_sha256` 纳入实际使用的配置路径 |
| P7 | `--baseline-only` 与 `--ab` 同时给被静默忽略 | `parser.error` 互斥 |
| P8 | 测试硬编码 golden 路径、守卫还原断言写成 `is not None`（恒真） | 改用 `dataset_path(cfg)`；断言还原为原函数对象 |

**复验**：`121 passed`（S6 的 97 + S7 的 24）、CI 门禁模拟 `PASS / degraded_case_ids=[]`、golden `--check` 同步、`uv sync --frozen` 与 `uv pip check` 103 包兼容、工作区干净。P1–P4 用同一批探针重跑：分别得到 `traceability=0.0 / fact_accuracy=1.0`、`expected_research_runs=3`、`passed=False + fewer_results:...`、两个独立指纹。**全程 0 次真实外部调用，未读取或使用 `TAVILY_API_KEY`。**

---

## 12. S8 真实实测行动方案（S8.0–S8.3 已完成首轮；S8.4 起待 golden 复核）

> S8.0 只读体检、S8.1 dry-run（0 调用）、S8.2 单次真实检索（2 credits）依次完成，
> 详见 `docs/LIVE_READINESS.md` 与 12.6 / 12.7 节。
> **用户 22:37 追加放行 20–50 credits 后，S8.3 已执行首轮**：1 次模型探针
> （0 Tavily credits）+ 1 家完整端到端真实报告（3 次检索 / 6 credits），
> 累计 **8 / 50 credits**、5 次模型请求。完整数字与失败案例见 **`docs/LIVE_FINDINGS.md`** 与 12.8 节。
> **S8.4 及之后仍未执行**：25 条 golden 草稿仍是 `human_verified_claims = 0`，
> AI 辅助复核表在 `evals/golden_live_review.jsonl`，最终 verdict 待用户逐条确认。
> S7 的 `1.000` 是合成语料契约回归分；S8.3 的真实报告里出现了自相矛盾的创立年份，
> **没有产出任何准确率数字**，简历数字必须来自可当场复现的实测。

### 12.1 为什么必须先问用户（3 个决策点）

| # | 待定项 | 为什么不能替用户决定 | 建议默认 |
|---|---|---|---|
| Q1 | 模型 key 用哪个 provider，是否允许产生费用 | 只从环境变量读，项目不存密钥；用户此前明确「谨慎使用、非必要不调用」 | **已拍板并实测**：阿里云百炼 DashScope `qwen-plus`（OpenAI 兼容端点）。`config/loader.py` 已加 `dashscope` provider；S8.3 真调 5 次 / 7896 tokens，`with_structured_output(function_calling)` 兼容 |
| Q2 | Tavily 免费额度放行多少 | 用户级 `TAVILY_API_KEY` 存在但当前进程未继承；`live` 需三重 opt-in | **S8.0 查到官方计费后修正**：`advanced`=2 credits/次、一次完整调研最坏 12 次 ≈ 24 credits/公司。建议先 `TAVILY_MAX_CALLS=1`（2 credits）只验返回结构，确认后再定 3–5 家的额度上限；缓存命中不扣 |
| Q3 | 真实 golden 谁标、标多少家 | 30–50 家 × 5 事实需要人工核验，不能由模型自己生成标准答案（会循环论证） | 先 5 家 × 5 事实跑通链路，确认口径后再决定是否扩到 30–50 家 |

### 12.2 分步任务与验收

| 步 | 动作 | 验收 / 产出 | 真实调用 |
|---|---|---|---|
| **S8.0** ✅ | 凭据与配置体检（**只读**）：进程是否继承各类 key、`live` 三重开关默认值、`.env` / `.gitignore`、上游 `/models` 出网风险、`AsyncTavilyClient.search` 静态签名 | `docs/LIVE_READINESS.md`；**只打印布尔值与长度，绝不打印 key 内容** | 0 |
| **S8.1** ✅ | dry-run 预演：`TAVILY_DRY_RUN=true` 跑一遍完整图，记录会发哪些 query、`CallBudget` 计数、sha256 cache key | `evals/live_dryrun.json`：12 条 query、预算计数、禁网与凭据探针全 0 | 0 |
| **S8.2** ✅ | 最小真实调用：`TAVILY_MAX_CALLS=1` 单 query，核对 `AsyncTavilyClient.search()` **真实返回结构**，结果落盘缓存 | **已完成**：`evals/live_probe.py` + `evals/live_probe.json` + `tests/test_s8_live_probe.py`；`response["results"]` 假设成立、3 条结果契约齐全、缓存可离线复现；详见 `docs/LIVE_READINESS.md` 第 8 节与 12.7 节 | **1 次 / 2 credits** |
| **S8.3** ✅ 首轮 | 端到端 live 小样本：先跑 **1 家**验证链路，记录 query 数、token、延迟、失败案例 | **已完成**：`evals/llm_probe.py`（模型兼容）+ `evals/live_run.py`（Notion 完整报告）+ `evals/live_quality.py`（0 调用词法检查）+ `docs/LIVE_FINDINGS.md`。3 次检索 / 6 credits / 4 次模型请求 / 62.9 s / 4998 字符；**自动抓到 1 处真实矛盾**（创立年份 2013 vs 2014）。未跑 3–5 家、未产出 p95 或成本单价（不编造） | **3 次 / 6 credits** |
| **S8.4** 🟡 前半完成 | 真实 golden + judge：按 Q3 把人工核验事实写成同 schema jsonl；把 `citation_traceability` 从词法代理升级为「自动词法 + 人工抽检一致率」，明确区分自动与人工 | 已产出 `evals/golden_live.jsonl` + `docs/GOLDEN_LIVE.md`；**「换 `EVAL_DATASET_PATH` 复用 S7」经实测不成立，见 12.9**，live 改走独立评分脚本；语义 judge 未做 | 0 |
| **S8.5** | 前后对比：fixture 契约回归 vs live 真实指标；如实写「fixture 满分 ≠ live 准确率」，列出拒答 / 错引 / 超时案例 | `docs/LIVE_REPORT.md` 对比表 | 可复用缓存 |
| **S8.6** | 简历数字出处表：每条数字 → 文件 + commit + 可复现命令 | `docs/RESUME_EVIDENCE.md`；无法当场复现的数字一律不写 | 0 |

### 12.3 硬约束（沿用前几阶段，不放松）

- 真实调用总次数 ≤ `TAVILY_MAX_CALLS` × 运行次数，且每次运行前先 dry-run；缓存命中优先。
- 密钥只从环境变量 / `.env` 读，**不写进任何提交文件、日志、scorecard**；`code_sha256` 不含密钥。
- 上游 `/models` 接口会出网（S5-B 审计结论）：live 体检时绕开或明确记录，不因为"看一下模型列表"白耗额度。
- `PostgresSaver` 目前未实现（`config/loader.py` 明确抛 `NotImplementedError`）：S8 用 SQLite 完成实测，不临时改持久化方案，除非用户另行要求。
- 不虚构甲方 / 上线 / 用户量；简历只写「本地实测」。
- 每个数字都要能由脚本与日志当场复现；复现不了就标「未测」。

### 12.4 降级路径

| 情况 | 能做到的部分 | 简历能写什么 |
|---|---|---|
| 无模型 key，但放行 Tavily | S8.0–S8.2（前两步已完成） | 「真实检索链路实测、返回结构与额度护栏」，**不能**写模型准确率/幻觉率 |
| 无模型 key，也不放行 Tavily | S8.0 + S8.1（均已完成）+ S9 的工程描述 | 只写架构与工程能力（图编排、checkpoint、评测台、0 调用预演），**不写任何效果数字** |
| 三者齐备 | 全部 S8.0–S8.6 | 真实指标 + 成本/延迟取舍，每条可复现 |

### 12.5 执行前检查清单（拍板后第一件事）

```bash
# 只读体检，不调用任何外部服务
uv run python -m evals.run_eval --baseline-only     # 确认 S7 基线仍 PASS
uv run pytest -q                                    # 121 passed 无回归
# 只打印布尔值/长度，不打印 key 内容
uv run python -c "import os; print({k: bool(os.getenv(k)) for k in ('TAVILY_API_KEY','OPENROUTER_API_KEY','OPENAI_API_KEY','GEMINI_API_KEY')})"
```

✅ 已执行：`--baseline-only` → `gate PASS`；`pytest -q` → `121 passed`；
进程环境检查 → 所有 key 与 live 开关均 absent（只打印存在性，未打印值）。

**用户放行记录**：21:20 放行 Tavily 2–20 credits、阿里云 `qwen-plus`、5 家×5 条待复核 golden，S8.2 按最小额度执行；**22:37 追加放行到 20–50 credits 并请求 AI 辅助复核**，S8.3 按「复核 0 credits → 模型探针 0 Tavily credits → 1 家完整报告 6 credits」执行。累计 8/50，剩余 42 未动；若扩到 3–5 家或再跑，仍需用户确认。

### 12.6 S8.0 / S8.1 执行记录（2026-11-14）

**S8.0 只读体检** → `docs/LIVE_READINESS.md`：进程未继承任何 key；`.env` 不存在、
`.gitignore` 已覆盖密钥/DB/缓存、`git ls-files` 无 secret 文件；上游 `/models`
（`application.py:217-232`）确认会出网，本阶段不启动 FastAPI 因而不触发；
`inspect.signature(AsyncTavilyClient.search)` 核对出 `search_depth` / `topic`
的字面量，项目配置值 `advanced` / `finance` / `news` / `general` **全部合法**
（此前口头说成"风险点"，核对后如实纠正）。最大未知仍是 `search()` 真实返回结构。

**体检坐实并修复 1 个真实缺陷**：`make_document_tool` 在 `TAVILY_DRY_RUN=true`
时仍无条件 `resolve_tavily_credentials()`，无 key 直接抛错，`.env.example` 承诺的
「先看会发哪些 query」根本跑不通。修法：dry-run 变成独立 0 请求路径 —— 不要 key、
不要放行额度、强制 `DryRunSentinel`、注入预算必须也是 `dry_run=True`；
真实调用的三重 opt-in **一点没放松**。附带把 `CallBudget.queries` 做成生产代码
路径上的 query 采集点，并给 `run_research` 加可选 `document_tool` 注入参数
（默认 `None` 时行为完全不变）。

**S8.1 dry-run 预演** → `evals/live_dryrun.py` → `evals/live_dryrun.json`：
跑完整图（`grounding → research×3 → curate → evidence_check → rewrite_query×2
→ degrade → briefing`），采集到 **12 条 query**（3 轮 × 4 栏目）+ 各自 sha256
cache key；`calls_made=0 / dry_runs=12 / cache_hits=0`、
`blocked_connection_attempts=0`、守卫已还原。三个入口（Tavily key 解析 /
模型 key 解析 / `AsyncTavilyClient` 构造）替换为计数器探针，实测**全 0**，
不是口头声明。两次独立运行逐字一致、提交产物与现场运行逐字一致。

**额度推算（非实测）**：官方 `basic=1` / `advanced=2` credits/次、免费 1000/月；
默认 `advanced` → 最坏 12 × 2 = **24 credits/公司**，3 家约 72（7.2% 月额度）。
`fast` / `ultra-fast` 官方该页未列单价，脚本标 `null` 并写明「拒绝猜测」，
已用反向探针验证，不沿用 advanced 的数字。

**复验**：`135 passed`（S6 97 + S7 24 + S8 14）；`uv pip check` 兼容；
工作区干净。**全程 0 次真实 Tavily / 模型调用，未读取或使用 `TAVILY_API_KEY`。**

**本阶段自我纠正 2 处**（避免把「看起来对」当成「做对了」）：
1. 初版脚本把 `socket_connect_restored` 写成 `connect is not None` —— 正是 S7
   复查时刚修掉的 P8 同款恒真断言，改成与原函数对象比较；
2. 初版给 `fast` / `ultra-fast` 也编了 2 credits，官方无依据，已改为标 `null`。
另把 query 清单按稳定键排序：4 个 analyst 由 `Send` 并行派发，到达顺序受调度影响，
不排序就无法保证跨机器逐字可复现。

**S8.0/S8.1 不产出任何真实准确率 / 延迟 / 成本 / 真实语料**，
`evals/scorecard.json` 的 `1.000` 仍是 fixture 契约回归分，不能写进简历。

### 12.7 S8.2 执行记录（2026-11-14 21:20–21:40，1 次真实调用 / 2 credits）

**用户拍板**：模型用阿里云百炼 `qwen-plus`；Tavily 放行 2–20 credits；
真实 golden 由助手查 5 家×5 条候选、用户复核。

**① 阿里云适配（0 调用）**：体检发现用户的 key 叫 `SYSTEM_ALIYUN_APIKEY`
（长度 117），另有 `BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`，
但 `config/loader.py` 的 provider 白名单只有 `openrouter/openai/gemini`，
且默认模型名是 `google/gemini-3.8-flash` —— **不改造根本接不上**。
改法：`LLMCredentials.provider` 增加 `dashscope`，`resolve_llm_credentials`
改为 `_LLM_PROVIDERS` 表 + `LLM_PROVIDER` 显式锁定（锁定后缺 key 直接抛错，
**不回退**到其他 key，避免误打到错误服务商白烧额度）+ `LLM_BASE_URL` 覆盖；
`settings.yaml` 的模型角色改用 `${LLM_MODEL:-...}`（默认值不变，历史行为不变）；
`.env.example` 写明运行时把用户变量映射为 `DASHSCOPE_API_KEY` 注入进程，
真实 key 不落盘、不提交。`tests/test_s8_dashscope.py` 10 例，含
`make_chat_model` 真构造 `ChatOpenAI` 核对 `model_name=qwen-plus` /
`openai_api_base=端点`，用 `MockTransport` + 禁网守卫保证 0 外部连接。

**② S8.2 单次真实检索（2 credits）**：`evals/live_probe.py` 用
`CallBudget(1)` + `RecordingClient`（第 2 次 SDK 调用直接抛错）双重上限，
经生产路径发 1 次 `advanced` 检索。实测 `calls_made=1`、
`sdk_search_invocations=1`、`cache_hits=1`（同 query 第二次命中缓存，0 额外扣费）。
详见 `docs/LIVE_READINESS.md` 第 8 节：`response["results"]` 假设成立，
3 条结果字段齐全，score `0.7174–0.8146`，`documents_from_results` 转出 3 个 Document。
产物 `evals/live_probe.json` 只含结构统计，正则核对无 `tvly-` / `sk-` 泄漏；
真实响应缓存在 gitignored `evals/cache/tavily/`。
`tests/test_s8_live_probe.py` 8 例用假 SDK 在**花钱之前**跑通完整探针逻辑，
含「缺字段响应不误判为通过」「无 key 时绝不构造 SDK」反向验证。

**③ 真实 golden 候选（0 credits，待用户复核）**：`evals/golden_live_draft.jsonl`
共 25 条（Notion / Figma / Stripe / Airbnb / Canva 各 5 条），
优先官方一手来源（Stripe newsroom、Figma blog、Airbnb IR、Canva 官方新闻稿）
与权威媒体（CNBC Disruptor 50）。meta 明确
`status=draft_pending_human_review` / `must_not_be_used_as_metric=true` /
`human_verified_claims=0`，`source_excerpt` 标注为「不保证逐字的定位线索」。
如实列出 **7 处来源冲突**（Notion 创始人 3 人 vs 6 人、估值 10B vs 11B；
Figma IPO 月份 7 月 vs 8 月；Stripe 成立年份 2009 vs 2010（已回避）、
支付额年度口径；Airbnb 2007 起源 vs 2008 成立；Canva 珀斯起源 vs 悉尼总部）。
`tests/test_s8_golden_draft.py` 7 例锁死：统计数字与真实数据一致、
25 条全部 `pending`、且**评测台数据集不得指向这份草稿**。

**④ 口径提醒（S8.4 必须先解决）**：真实模型报告不会与 `candidate_fact` 逐字一致，
S7 的精确文本匹配 `fact_accuracy` 在真实语料上会失效；S8.4 需引入语义 judge
或人工判定，不能把草稿直接接进 `run_eval.py` 出「准确率」。

**自我纠正 2 处**：草稿初版把 Canva 法文原文混写成西语（凭记忆补引文），
已改为对应法文版页面与原文，并在 meta 加 `excerpt_fidelity` 说明所有摘录只是
定位线索、不保证逐字；`review_summary` 的来源计数原为手算（16/5/4），
用脚本重算后修正为 `official=12 / press_release=5 / media=5 / aggregator=3`。

**复验**：`160 passed`（S6 97 + S7 24 + S8 14 + 适配 10 + 探针 8 + 草稿 7）、
golden `--check` 同步、scorecard 因配置/代码变更重生成且门禁 `PASS`、
`live_dryrun.json` 与现场运行一致、`uv pip check` 103 包兼容。
**12.7 节当时快照**：累计 1 次 Tavily（2 credits）、0 次模型；未超过当时的放行上限 20。
**仍未产出任何真实准确率 / 幻觉率 / 延迟 / 成本数字。**
（当前累计以 12.8 节 / `docs/LIVE_FINDINGS.md` 为准。）

### 12.8 S8.3 执行记录（2026-11-14 22:37 起；累计 8 / 50 credits）

**① AI 辅助复核（0 credits）**：逐条打开 9 个原始 URL 读页面原文，产出
`evals/golden_live_review.jsonl`（25 条逐条证据）+ `docs/GOLDEN_REVIEW.md`（5 分钟可点完的清单）。
结果 `verified=15 / needs_fix=8 / reject=2`；**3 个原 URL 打不开**（2 个 Business Wire 返回
Page Unavailable、`wikipedia.com` 抓取失败且非官方域名）。两处冲突用官方一手来源彻底解决：
Figma IPO 以 [官方定价公告](https://www.figma.com/blog/ipo-pricing/) 为准是 **2025-07-31 开始交易**（8 月 1 日交割，所以二手站写「August」不算错但口径含糊）；
Airbnb 2007 vs 2008 是「起源 vs 正式上线」的口径差异，官网时间线两条都有。
另查出 `notion:financial:0` 的那段融资文字在 CNBC 2026 与 2025 两版全文均 **NOT FOUND**
（疑似旧版/搜索摘要），建议改写并换 URL。**复核表全程 `human_verified_claims=0`、
25 条 `user_verdict` 全 `null`**，8 例护栏测试锁死「评测台不得读草稿/复核表」。

**② 模型侧未知坐实（0 Tavily credits）**：`evals/llm_probe.py` 用 1 次 `qwen-plus` 请求
（748 tokens / 3.8 s）验证 `with_structured_output(method="function_calling")` 在百炼
OpenAI 兼容端点可用，返回合规 `SectionBrief`，3 条 fact 的 URL 全部回溯到给定文档。
S5-B 起标注的「模型侧只做了 0 调用构造验证」至此消除。

**③ 端到端真实报告（6 credits）**：`evals/live_run.py` 跑 Notion 完整图，
`TAVILY_MAX_CALLS=12` + `CallBudget(12)` 双硬预算、累计 credits 超 50 直接作废结果。
实际 **3 次真实检索 + 1 次缓存命中**（4 栏目各 1 query，首轮全 sufficient，未触发自纠正）、
**4 次模型请求 / 7896 tokens / 62.9 s / 4998 字符报告**、27 条结论 / 11 条 References /
四栏目齐全 / 无降级。累计 **8 / 50 credits**。可用缓存 4 份，均在 `.gitignore` 内。

**④ 失败案例（本阶段最重要，不能藏）**：`evals/live_quality.py`（0 调用词法检查）
自动抓到 `Company Overview` 里**同时写着 founded in 2013 与 founded in 2014**；
人工阅读另见「总部在伦敦」「前身 Canopy Technologies」「约 1200 员工」等未核验表述，
11 个来源含 `medium.com` 等非一手渠道。`citation_integrity_ok=true` 只证明 27 个 `[n]`
都有对应编号，**不证明**该 URL 支持结论。这坐实了「fixture `1.000` 掩盖真实语料噪声」，
是待修复项，不是成果。

**⑤ 自我纠正 5 处**：复核表 claim 行漏 `kind` 导致统计脚本 `KeyError`；
`summary` 手写 `16/7/2` 与脚本算出的 `15/8/2` 不符；
`live_run.py` 行内引用正则把 References 段的 `[n]` 也数进去（10 vs 5），改为只数正文；
`live_quality.py` 栏目归属从「文本反查」改成按 `##` 分段解析；
`llm_probe.py` 的 Tavily 哨兵改成 contextmanager（退出还原，避免污染同进程）、
Pydantic `model_fields` 改用类属性避免弃用告警。

**⑥ 如实边界**：1 家公司 1 次运行，**没有**真实准确率 / 幻觉率 / p95 / 成本单价
（`total_cost_usd=null`，qwen-plus 不在 OpenAI 价目表内，不套用不编造）；
25 条 golden 仍 `human_verified_claims=0`，S7 逐字匹配对真实报告不适用（S8.4 需语义 judge）。
剩余 **42 credits** 未动；是否扩到 3–5 家、是否再跑，均由用户决定。

### 12.9 S8.4 前半执行记录（2026-11-15 00:13，0 调用 / 0 credits）

用户拍板「25 条内容就是正确的，我查了」= 事实层人工核验通过，导出
`evals/golden_live_review_filled.jsonl`（25 条全 `accept`、1 条文字备注）。

**已产出**：`evals/build_golden_live.py` → `evals/golden_live.jsonl`（1 meta + 5 case + 25 claim）、
`docs/GOLDEN_LIVE.md`（三层边界口径）、`tests/test_s8_golden_live.py`（9 条护栏）。
如实标注三层：**事实层**用户已核验；**引用层**未核验（6 条 URL 打不开、10 条与 AI 核对结论冲突）；
**覆盖层**只有 Notion 1 家 5 条有真实报告，其余 4 家 20 条无报告可比。AI 的核对结论原样保留供审计，
不因与用户结论冲突就删除；用户备注也原样带进正式 golden。

**修正原计划的一处错误**：12.2 写的「换 `EVAL_DATASET_PATH` 即可复用 S7 脚本」
经 `uv run python` 只读探针实测不成立，三处硬冲突（详见 `docs/GOLDEN_LIVE.md` 第 3 节）：
① live golden 无 abstain 样本，`evals/run_eval.py` L205-206 直接拒绝；
② `config/eval.yaml` 的 `provenance` 写死 `synthetic-fixture-derived`，与 `human-verified` 冲突；
③ `fixture.cases = sufficient/sparse/empty` 与 5 个公司 case 不匹配（L210-212）。
→ S7 继续只跑 fixture golden；live 改走独立评分脚本，**不硬凑拒答样本**。

> 注：以下是 12.9 写就时的历史快照；S8.4 语义 judge 的实际完成情况见 **12.11**。

**仍未做（S8.4 后半 + S8.5/S8.6/S9）**：
- 语义 judge：中文 golden vs 英文报告，逐字匹配必 0。方案 A = `qwen-plus` 批量判定
  （约 1 次模型请求 / 0 Tavily credits，需用户放行）；方案 B = 0 调用锚点弱代理
  （必须显式标 `is_semantic_judge=false`，不得写成语义准确率）。
- `docs/LIVE_REPORT.md` fixture vs live 对比表；`docs/RESUME_EVIDENCE.md` 数字出处表；S9 简历。
- 真实准确率 / 幻觉率 / p95 / 成本单价仍为「未测」，不得写进简历。

### 12.10 用户二次复核：按 25 条最终答案重建 golden（2026-11-15 11:47，0 调用 / 0 credits）

- 用户重新复核并把部分条目改成最终标准答案，重新导出 `evals/golden_live_review_filled.jsonl`：
  **14 采纳原样 / 11 按建议修正 / 0 驳回**，25 条全部带备注；`accepted_but_conflicts_with_ai_check = 0`。
- 用户还改了 `evals/build_review_page.py`：加 `PRESETS` 预填「修正后的事实 / URL / 备注」，
  但**不预填 decision**，三个结论按钮仍由用户逐条点（脚本注释与页面说明均写明）。
  这份改动保留，未被覆盖。
- 11 条修正里，6 条打不开的原始 URL（Canva 5 条 Business Wire、`wikipedia.com` 镜像）
  全部换成新 URL；Figma IPO 月份改官方口径、Airbnb「已上市」改「公告预计」、
  `notion:financial:0` 由用户自行指定 SiliconANGLE 出处（AI 建议的 CNBC 2025 版未采用）。
- 重写 `evals/build_golden_live.py` → 重建 `evals/golden_live.jsonl`：每条同时留
  `expected_text/source_url`（最终版）与 `original_fact/original_source_url`（草稿），
  换过 URL 的 `source_content=null`；`final_url_sources` 区分
  original 16 / ai_suggested_and_read 7 / user_supplied 2。
  **引用层仍标不可算指标**：新页面本项目没抓过（0 调用），不能把旧引文冒充新页面内容。
- 同步更新 `docs/GOLDEN_LIVE.md`（三层边界、14/11 统计、最终 URL 来源）与
  `tests/test_s8_golden_live.py`（把写死的 25/6/10 改成从输入动态推导，新增
  「旧草稿不得覆盖用户最终措辞」「6 条原始 URL 全部替换」「换 URL 不得伪造页面内容」护栏）。
  全量 **206 passed**。0 调用 0 credits，Tavily 仍 8/50。
> 注：本节末段的「下一步」是 12.10 写就时的历史快照；S8.4 已于 12.11 完成，
> 复查与修复见 12.12。

- 下一步不变：S8.4 语义 judge（中文答案 vs 英文报告，待用户放行 1 次 `qwen-plus` 或走 0 调用弱代理）
  → S8.5 对比表 → S8.6 数字出处表 → S9 简历。仍无真实准确率 / 幻觉率 / p95 / 成本单价。

### 12.11 S8.4 语义 judge 完成（2026-11-15，1 次模型请求 / 0 Tavily credits）

本节更新 12.9 / 12.10 的待办状态。用户放行 **方案 A（1 次 `qwen-plus`）+ 只批 Notion**，
不扩样本、不动 Tavily 额度。

**产出**：
- `evals/judge.py`：三重放行（`--live` + `JUDGE_LIVE=1` + `DASHSCOPE_API_KEY`）、
  `max_retries=0` 锁定 1 次请求、Tavily 哨兵、prompt 只送 `claim_id`+`expected_text`
  （不送出处/AI 备注）、证据句必须报告逐字可核、失败如实落盘不重试。
- `evals/live_score.json`：唯一真实结果；`evals/live_score_dryrun.json`：0 调用占位，
  标 `must_not_be_used_as_metric=true`。
- `docs/LIVE_SCORE.md`、`tests/test_s8_judge.py`；同步 `docs/GOLDEN_LIVE.md` 第 4/5/6 节。

**真实运行**：1 次请求、2776 tokens（2334/442）、0 Tavily 调用 / 0 credits、
Tavily 累计仍 **8/50**；`total_cost_usd=null` 不编造单价。5 条全判定：
`supported=0 / refuted=2 / not_mentioned=3 / self_conflict=1 / quote_check_failed=0`，
20 条如实跳过。独立精确子串复核：3 条引文全部逐字命中报告原文。

**真机报告被抓出 3 类硬伤**（fixture 满分测不出）：同栏目 2013/2014 自相矛盾；
总部写成伦敦门牌 + 混入 `medium.com`；Financial 栏目 11 条全是马来西亚上市公司
`Notion VTec Berhad (0083.KL)` 的股票指标（实体混淆）。记为已知问题，不阻塞 S8.5/S9。

**如实记录的缺陷**：`notion:company:2` 的 judge reason 说「未提 Ivan Zhao as CEO」，
但报告 Industry 栏目出现过一次 `CEO Ivan Zhao's 'Legos' analogy`。判定本身仍成立
（未列创始人/未提另两人），但措辞不精确 —— 这正是 `is_human_adjudicated=false`、
`usable_as_resume_metric=false` 的实证理由，不删结果、不重跑。

**仍未做（S8.5 → S8.6 → S9）**：`docs/LIVE_REPORT.md` fixture `1.000` vs 真机判定对比表
（0 调用）；`docs/RESUME_EVIDENCE.md` 数字出处表；3–4 条简历描述 + 面试追问清单。
真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价**仍为「未测」**，不得写进简历。

### 12.12 S8.4 复查：6 个问题及修复（2026-11-15 12:22，0 调用 / 0 credits）

用户按惯例要求「先检查上一步有没有问题」。只读探针逐个坐实，**不是静态翻看**：

| # | 问题 | 坐实 | 修复 |
|---|---|---|---|
| 1 | References 标题能冒充正文证据句 | Forbes 标题在 References、不在正文，旧 `quote_in_report` 返回 `True` | 新增 `report_body()`，只在 `## References` 之前核 |
| 2 | `not_mentioned` 塞编造引文不标失败 | 塞 `"THIS IS INVENTED BY JUDGE"`，`quote_check_failed=False` | 任何 verdict 有核不到的引文一律标失败 |
| 3 | schema 缺条目时 `status` 仍 `ok` | 只返回 1/5 条，`status=ok` 但 `unjudged=4` | 改 `partial`，与 `main()` 返回码一致 |
| 4 | 前置检查失败不落盘 | `common_inputs()` 等在 `try` 外，异常直接冒泡 | `main()` 兜底写独立 `live_score_failed.json`，不覆盖成功产物 |
| 5 | 产物无输入/代码指纹（S7 已有 `code_sha256` 先例） | `has_any_hash_field=False` | `judge.py` 加运行时 `fingerprints()`；既有产物由审计事后补记 |
| 6 | 跨盘符路径让 `relative_to(ROOT)` 抛错 | 新增护栏测试实测失败 | 打印改用文件名 |

另修两处措辞：自动校验是「归一化后比对」而非「原始逐字」；`LIVE_SCORE.md` §2
表格列名对 `not_mentioned` 行不成立。总表 S8 状态同步为 S8.0–S8.4 完成。

**新增**：`evals/audit_score.py` + `evals/live_score_audit.json`（0 调用事后审计）、
`tests/test_s8_judge.py` 扩到 25 条、`tests/test_s8_score_audit.py` 5 条。
审计结论：按新口径重算 5 条，`delta_vs_original=[]`、`verdicts_changed=[]`，
**0 差异，既有判定与 3 条正文引文全部不受影响**；原始 `live_score.json` 一字未改，
用 `source_artifact_sha256` 锚定。指纹标 `recorded_after_run=true`，
`judge_py_at_run_commit_sha256` 取自 git `3e16906`，如实说明是事后补记、
不等价于运行时采集。详见 `docs/LIVE_SCORE.md` §7。全量 **236 passed**，Tavily 仍 8/50。

### 12.13 S8.5 fixture vs 真机对比表（规划；已执行，结果见 12.14）

**目标**：一份能当场复现的 `docs/LIVE_REPORT.md`，把「假数据满分」与「真机表现」
并排讲清楚，作为 S8.6 简历数字出处表的事实底座。

**输入全部已存在，0 调用 / 0 credits，不重跑模型、不扩样本、不动额度**：
`evals/scorecard.json`（`runs.baseline.metrics`）、`evals/live_run.json`（Notion 真机报告）、
`evals/live_quality.json`（词法检查）、`evals/live_score.json`（5 条 AI 判定）、
`evals/live_score_audit.json`（§7 审计）、`evals/live_dryrun.json`（预算推算）。

**12:22 只读探针先核实了输入可用，并发现一处必须写进红线的口径风险**：
`scorecard.json` 的 `runs.baseline.metrics` 里就有 `fact_accuracy=1.0`、
`citation_traceability=1.0`、`hallucination_rate=0.0`、`p95_latency_ms=2379.819`、
`cost_per_report=0.0`，但全部来自 **fixture 合成语料 + 0 外部调用**（文件自带
`disclaimer` 已声明）。数字不是顶层字段，藏在 `runs.baseline.metrics`，
对比表要按这个字段路径取，且**绝不能把 `2379.819 ms` 当真实 p95、
把 `0.0` 当真实成本**引用。准确口径：fixture 侧有值、真机侧全部未测。

**产出与验收**：
1. 对比表：逐项列「fixture 测什么 / 真机看到什么 / 差距说明」，每个数字标出处文件 + 字段；
2. 已知问题清单：`LIVE_SCORE.md` §4 的三类硬伤 + judge 措辞瑕疵，写成可讲的项目发现；
3. 「不能写成什么」清单：`1.000` ≠ 效果好、`supported=0` ≠ 准确率 0%、
   不编造 p95 / 成本单价 / 幻觉率；样本量 1 家 5 条必须写明；
4. 复现命令与 CI 护栏：新增 `tests/test_s8_live_report.py`，断言对比表里每个数字
   能从对应产物字段重算出来，禁止手写死数字；
5. 全量测试通过、`uv pip check` 通过、Tavily 仍 8/50。

**之后**：S8.6 `docs/RESUME_EVIDENCE.md` 数字出处表 → S9 三条简历描述 + 面试追问清单。
真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价仍为未测，全程不得写进简历。

### 12.14 S8.5 执行结果：fixture vs 真机对比表（2026-11-15，0 调用 / 0 credits）

**产出**：`evals/build_live_report.py`（生成脚本）、`docs/LIVE_REPORT.md`（对比表）、
`tests/test_s8_live_report.py`（15 条护栏）。另给 `docs/LIVE_FINDINGS.md` 加**状态注记**：
其 §4–§6 描述的是 S8.3 当时的未完成项，原文保留不改以维持时间线真实，
当前口径指向 `GOLDEN_LIVE.md` / `LIVE_SCORE.md` / `LIVE_REPORT.md`。

**做法**：只读 6 份既有产物，装 `eval_offline_guard`（实测拦截 **0** 次外部连接）；
模板里不写死任何数字，71 个表格单元格里 55 个数值由 `Cell(key, path, value)` 携带出处，
测试按「文件 → 字段」逐项重算。**变异探针验证**：把 `fact_accuracy` 改成 `0.42`
或把 `credits.cumulative` 改成 `99`，生成结果都跟着变 —— 文档确实绑定产物，不是碰巧对上。

**文档结构**：§1 口径差异（fixture 合成语料 + 0 外部调用 vs 真机真实网页 + 4 次模型 / 3 次检索）；
§2 八个指标逐项写「fixture 侧有值、真机侧未测」，特别隔离
`p95_latency_ms=2379.819` 与 `cost_per_report=0.0` 这两个最易被误用的 fixture 数；
§3 真机实测事实逐项标出处；§4 用 A/B 三组证明 `1.0` 是流程契约分
（关行内引用 → traceability 掉到 0、hallucination 升到 1，事实准确率纹丝不动）；
§5 三类硬伤 + judge 措辞瑕疵；§6 七条红线；§7 简历可写的工程事实；§8 产物索引；§9 状态。

**验收**：全量 **251 passed**、`uv pip check` 103 包兼容、Tavily 仍 **8 / 50**、
本轮 0 次模型请求 / 0 credits、密钥零泄漏（历史文档里仅有 `sk-` 正则说明文字）。
S8.5 只做记录与对比，**不修硬伤、不复测**（复测需另花额度，单独规划）。

**阅读提示**：12.0–12.13 各节末尾的「仍未做 / 下一步」是**当时的快照**，
保留不改以维持决策时间线；当前状态以**总表 S8 行**与本节为准。

**下一步 S8.6**：`docs/RESUME_EVIDENCE.md` 简历数字出处表 → S9 三条简历描述 + 面试追问清单。
真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价仍为「未测」，不得写进简历。
【S8.5 历史快照：S8.6 已完成，见 12.15】

### 12.15 S8.6 执行结果：简历数字出处表（2026-11-15，0 调用 / 0 credits）

**产出**：`evals/build_resume_evidence.py`（生成脚本 + `--verify` 批量复现）、
`docs/RESUME_EVIDENCE.md`（出处表）、`tests/test_s8_resume_evidence.py`（67 条护栏）。
另给 `docs/LIVE_REPORT.md` §9、`docs/LIVE_SCORE.md` §6、`docs/LIVE_FINDINGS.md` 开头
补**状态注记**：历史快照原文保留，指向当前口径文档。

**做法**：只读 10 份既有产物，装 `eval_offline_guard`（实测拦截 **0** 次外部连接）。
收录 **25 条**可复现数字，分 A 真机实测 / B 评测工程 / C 额度纪律三组，
每条给出 值 + 出处文件与字段 + 该文件最后修改的 commit + 一条独立可执行的 `python -c` 复现命令。
命令由 (文件, 字段路径) 自动生成，**不 import 生成脚本本身**，避免自证循环；
commit 由 `git log -1 --format=%h -- <文件>` 现场取得，上游归因 commit 从 `docs/UPSTREAM.md` 读取。
`--verify` 对 25 条**逐个起子进程真的执行命令**，stdout 与产物取值逐字比对 → **25 / 25 PASS**。

**口径修正（自查发现并已改）**：`scorecard.summary.groups_run` 长度含 baseline，
原措辞「6 组 A/B 对照」已改成「6 个评测组（含 baseline 与开关 A/B 组）」；
§2.1 里手填的「仅 1 份」改为由 `live_run.company` 推导；
F03 / F17 / F24 措辞里混入手填数字改为引用字段或去掉；
F13 中英混排标签订正。禁写清单 **9 条**同样带出处与 commit，覆盖
fixture 准确率 / p95 / 成本 / 幻觉率、AI judge 结果、引用可追溯率、
「独立开发」「上线 / 甲方 / 用户量」等归因与真实性红线。

**验收**：全量 **318 passed**、`uv pip check` 103 包兼容、密钥零泄漏、
Tavily 仍 **8 / 50**、本轮 0 次模型请求 / 0 credits。
变异探针验证：改 `live_run.credits.cumulative` 或 `scorecard.external_calls.tavily`，
渲染结果都会跟着变 —— 文档确实绑定产物。
（注：`fact_accuracy` 只出现在禁写清单里、不引用数值，改它文档不变属预期，测试注释已写明。）

**边界不变**：真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价仍为「未测」；
本表只保证「写出来的数字查得到」，不保证「系统效果好」。

【S8.6 历史快照：本节记录首次生成的 25 条；复查后已扩到 30 条，见 12.17】

### 12.16 下一阶段规划：S9 简历交付（待用户放行执行）

**目标**：`docs/RESUME.md`，3–4 条可直接粘贴的简历项目描述 + 面试追问清单。
**0 调用 / 0 credits**，只读取既有文档与产物，不新增测量、不扩样本、不修硬伤。

1. **每条描述指回出处**：句中的每个数字标注 `RESUME_EVIDENCE.md` 的编号（如 `F01/F04/F13`）
   与对应 commit；技术点标注具体代码文件（图编排 / 结构化输出 / Retriever / HITL / 评测台）。
2. **内容边界**：只写架构与工程能力、人工核验数据链路、真机发现的三类硬伤（作为「发现并定位问题」）、
   额度纪律；**不写**准确率 / 幻觉率 / p95 / 成本单价 / 提升 X% / 上线 / 甲方 / 用户量，
   不写「独立开发」（Apache-2.0 二次开发归因）。
3. **面试追问清单**：按「为什么这么设计 / 数字怎么来的 / 哪里还不行 / 怎么复现」组织，
   每个回答指向具体文件与命令；重点准备 `1.0` 为什么只是契约分、`supported=0` 不是准确率 0%、
   真机实体混淆为何没被测出来、引用层为何未核验。
4. **验收**：新增 `tests/test_s9_resume.py`，断言简历里出现的每个数字都能在
   `RESUME_EVIDENCE.md` 找到编号、禁用词表为空、归因声明存在；
   全量 pytest 与 `uv pip check` 通过，Tavily 仍 8/50。

**四条描述的主题（每条只讲一件事，避免堆砌）**：

| # | 主题 | 主要证据 |
|---|---|---|
| 1 | 图编排与自纠正：LangGraph 子图并行检索、条件边路由、栏目级 retry、checkpoint、HITL 中断/恢复 | `graph/builder.py`、`graph/subgraphs/research.py`、`graph/nodes/`、`tests/test_s6_hitl.py` |
| 2 | 可信度与评测：人工核验 golden、AI 语义批改、fixture vs 真机对比、A/B 回归门禁 | `evals/golden_live.jsonl`、`evals/judge.py`、`evals/build_live_report.py`、`.github/workflows/eval.yml`；F13/F17/F21/F22 |
| 3 | 真实链路与额度纪律：三重 opt-in、禁网守卫、调用预算、缓存 | `capabilities/tavily_retriever.py`、`evals/run_eval.py`、`evals/live_dryrun.json`；F01/F02/F04/F05/F12/F30 |
| 4 | 问题定位：真机报告三类硬伤（自相矛盾 / 来源污染 / 实体混淆）与「引用编号对得上 ≠ 事实对」 | `docs/LIVE_FINDINGS.md`、`evals/live_quality.json`、`docs/LIVE_SCORE.md`；F08/F09/F10 |

### 12.17 S8.6 复查结果：补 5 个漏收数字并加固失败路径（2026-11-15，0 调用 / 0 credits）

用户按惯例要求「先检查上一步、有问题解决、不知道就问、好了再规划下一阶段」。
用只读探针复查，坐实 **3 个真问题 + 1 处措辞不精确**，全部修复：

1. **漏收 5 个简历真会用的数字**（最实质的问题）：原表 25 条只有单次报告 4 次模型请求，
   但 `12.15` 与总表已写「累计 6 次模型请求」，简历若照写就**查不到出处**。
   探针另外发现「4 个栏目」「8 项评测指标」「3 个 fixture 用例」「23 条 fixture claim」
   都是简历常用工程数字，却一条未收。已补 F26–F30：
   栏目数 4（`live_run.config.sections`）、指标项数 8、fixture 用例 3、fixture claim 23
   （均在 `scorecard.runs.baseline`）、累计模型请求 6（`llm_probe` + `live_run` + `live_score` 三处求和）。
   **为跨文件求和扩展 `Fact.sources` / `derive_all`**，复现命令按顺序加载为 `d0/d1/d2`；
   出处列与 commit 列同时列出 3 个文件，不再只标主文件。
2. **`--verify` 失败路径会整批崩**：删掉 `live_run.credits.cumulative` 后探针得到
   `KeyError` 直接抛出，其余 29 条都跑不到，「哪条断了」被一个 traceback 掩盖。
   已改成逐条 `try/except` → 该条 `ok=False` 并记下异常类型，其余照跑；
   新增护栏断言「一条坏字段不影响其余条目，且 F01 明确 FAIL」。
3. **F14 的边界指向不精确**：「其中仅 1 家有真实报告可比，见 F17」，
   但 F17 是「可对答案 5 条」、不是「1 家」。改为「仅 `live_run.company` 一家有真实报告；
   可对答案的条数见 F17」，不再拿条数冒充家数。
4. **§7 写「三条简历描述」与任务表「3–4 条」不一致**：统一为 3–4 条。

**验收**：`--verify` **30 / 30 PASS**；`tests/test_s8_resume_evidence.py` 从 67 条增至
**79 条**（新增跨文件求和自洽、失败路径、多源出处完整性）；全量 pytest 通过；
`uv pip check` 103 包兼容；Tavily 仍 **8 / 50**；本轮 0 次模型请求 / 0 credits。
12.15 保留为首次生成的 25 条快照并加注记，不篡改历史。


### 12.18 S8.6 复查（续）：commit 列每提交一次就失效（2026-11-15，0 调用 / 0 credits）

用户说「开始」之前按惯例复查上一步，**全量测试在 HEAD 上就是红的**，不是环境问题：

- 失败用例：`tests/test_s8_resume_evidence.py::test_document_is_exactly_the_rendered_output`。
- 现象：文档里 `docs/ACTION_PLAN.md` 的 commit 是 `6fb301e`，而 `render()` 现算得到 `076a992`
  （12.17 那次提交改过该文件）。
- 根因：commit 列每次渲染都现场跑 `git log -1 --format=%h -- <文件>`，但文档是**提交前**生成的。
  于是「任何一次提交，只要改到被引用的文件，文档与 render 就必然不一致」——测试永远只能
  在脏工作区里通过，提交即红。S9 还要继续改 `docs/ACTION_PLAN.md`，不修就交不了。

**修法**：把「录入时该文件的最后一次修改提交」冻结进 `evals/resume_evidence_commits.json`
（14 个文件，含产物与文档），渲染只读台账；新增 `--record-commits` 作为唯一刷新入口。
这不降低可信度，反而更贴近简历语义——**数值在那个 commit 里确实存在**，而不是「文件后来又被改过」。

**护栏同步加强**（不是把断言改松）：
1. 每条数字用 `git show <commit>:<文件>` 回到台账标注的版本，按同一路径重算 → 必须与当前值一致；
   先跑只读探针确认 31 条在各自 commit 下 **0 mismatch**，再固化成测试。
2. commit 必须是 `HEAD` 的祖先（不能指向未来），且该 commit 下文件必须存在。
3. 台账必须覆盖全部被引用文件（产物 + `docs/UPSTREAM.md` / `docs/ACTION_PLAN.md` /
   `docs/LIVE_REPORT.md` / `LICENSE`）。
4. 把 `live_commit` 打成必炸后 `render()` 仍须成功——直接钉死「渲染不许现场问 git」。

**验收**：S8.6 护栏 **111 条**通过；全量 **362 passed**；`uv pip check` 103 包兼容；
Tavily 仍 8 / 50；本轮 0 调用。**提交后复验 `doc == render` 通过**——这正是旧版本做不到的那一步。

### 12.19 S9 执行结果：简历描述与面试追问（2026-11-15，0 调用 / 0 credits）

**产出**：`evals/build_resume.py`（生成脚本）、`docs/RESUME.md`（交付物）、
`tests/test_s9_resume.py`（17 条护栏）。另给出处表补一条 `F31`（advanced 单次计费），
让「按官方规则 2 credits/次」这句话也有编号可指。

**结构**：§1 可直接粘贴的 4 条（图编排 / 评测与人工核验 / 真实链路与额度 / 问题定位）；
§2 每条展开成技术细节 + F 编号 + 代码位置；§3 18 条面试追问（设计取舍 7 / 数字口径 5 /
问题定位 4 / 复现与额度 2），每答都指到文件；§4 不能写的话；§5 复现命令；§6 状态与边界。
归因按 `docs/UPSTREAM.md` 现场读取上游 commit，写「Apache-2.0 二次开发」，不写「独立开发」。

**数字纪律（这是本阶段的核心）**：模板里禁止出现裸数字，只能写 `{F31}` 这样的占位符，
渲染时从 `build_resume_evidence` 的同一套 `Fact` 取值。因此「简历上的数字查不到出处」
在结构上不可能发生，而不是靠人工核对。渲染后再查一遍：除代码、编号、章节号、指标名
（`p95`）与许可证名（`Apache-2.0`）外，正文里的每个数字都必须命中出处表。

**变异探针**：往 `docs/RESUME.md` 末尾手写一行「准确率 100%」→
`test_document_is_exactly_the_rendered_output` 与 `test_every_number_in_document_comes_from_the_evidence_table`
**同时 FAIL**；改 `golden_live.claims_revised_by_user` 或 `live_run.credits.user_ceiling`，
渲染结果跟着变。恢复后 17 / 17 通过。

**如实边界**：仍然 0 次模型请求 / 0 credits；真实准确率 / 幻觉率 / 引用可追溯率 / p95 /
成本单价**仍未测**，简历里也只写「未测」。这份材料只保证「写出来的每个数字查得到」，
不保证「系统效果好」——后者需要扩样本重跑，另算额度。

**验收**：全量 **382 passed**；`--verify` **31 / 31 PASS**；`uv pip check` 103 包兼容；
Tavily 仍 8 / 50。

**下一步（可选，需用户拍板）**：① 扩到多家真实报告（要 Tavily credits + 模型调用）；
② 实体消歧与冲突前置两个修复（改图，不动额度）；③ 把 `docs/RESUME.md` 的 4 条按目标岗位
（Agent 工程 / RAG / 后端）各出一版侧重点不同的措辞。

### 12.20 S10 执行结果：同名实体消歧 + 同栏目冲突前置（2026-11-15，0 调用 / 0 credits）

用户在三个可选项里选了「① 修两个硬伤 → ② 扩真实样本 → ③ 多版措辞」，本节只做 ①。
**本轮 0 次 Tavily 调用、0 次模型请求**，全部验证都用已有的真实检索缓存在离线完成。

#### 12.20.1 先纠正一个判断：那两个症状是同一个根因

S8.4 当时把真机报告的三处硬伤分别记成「自相矛盾」「事实错」「实体混淆」。
这次回看 `evals/cache/tavily/` 的**原文**（不是报告里的转述），发现前两处是同一件事：

`cbinsights.com/company/notion` 那一页正文写着 `notion.online`、
"editorial publishing and curation within the music, fashion, and creative industries"、
"founded in 2014 and is based in London, England"、"51 Lloyd Baker Street" ——
那是**一家做音乐时尚内容与半年刊杂志的英国公司**，和做协作工具的那个 Notion 只是重名。
所以「2013 与 2014 矛盾」「总部写成伦敦门牌」不是来源打架，是**两家公司被当成一家**。

这条纠正很重要：如果按原判断去做「按置信度选一条」，真机里 CB Insights 的 score 是 0.77、
PitchBook 是 0.72，会保留**错的**那个（Notion 实际成立于 2013 年）。**用置信度替读者
做决定，在来源本身就错的情况下比并列更糟。**

#### 12.20.2 实现：三条规则 + 两道护栏

新增 `capabilities/entity_guard.py`，接在 `curate` 的最前面（阈值判定之前）——
名字不对的文档不该占用证据预算，也不该出现在 References 里。

| 规则 | 判据 | 真机命中 |
|---|---|---|
| `ticker_binding` | 标题里 `{公司名} <扩展名> (<交易所代码>)` 且扩展名含**法域后缀**（Berhad/Bhd/Pte/GmbH/AG/…） | `Notion VTec Berhad (0083.KL) Valuation Measures` |
| `listing_page` | 标题扩展名含法域后缀 **且** 正文命中 ≥2 个股票行情词（无 ticker 括号时兜底） | 同上（主规则失效时才用） |
| `incoherent_profile` | 同栏目两篇文档的**官网域名无交集**，且其中一篇的**成立年份不是栏目多数** | `notion.online` / 2014（栏目多数 2013） |

**刻意不做的事**：不猜 `Sia Partners buys … Notion Consulting` 这类同名不同业务的公司。
它们没有行情页特征、也没有域名冲突，任何纯字面规则都会误杀 —— `Notion Labs, Inc.` 就是
Notion 自己注册的实体名。这类留在报告里，如实标为「检索相关性」问题而非实体问题。

**两道护栏**：
1. **全灭护栏**：某栏目所有文档都被判异实体 → 说明规则在这家公司名上失效（例如用户调研的
   正是那家带法域后缀的外国公司）→ 全部放行并留痕 `all_rejected_fallback`。隔离器不许清空栏目。
2. **开关必须两阶段都停**：第一版只让单文档规则看 `features.entity_guard`，跨文档一致性还在
   偷偷改证据集 —— 离线回放对照时发现「关掉的版本也拒了 cbinsights」，才补上。

#### 12.20.3 冲突前置：第二道防线，只标注不改写

新增 `capabilities/conflict.py`，在 `features.structured_output=on` 的路径上工作，
检测三个槽位：成立年份 / 总部位置 / 员工人数（后者只标不判——同一公司不同年份员工数本就不同）。
检出冲突时在该栏目末尾追加一行 markdown 引用块：

```
> **来源冲突**：成立年份出现 2 个取值 —— 2013 [6] / 2014 [4]，来源之间不一致，未判定哪个正确
```

四个刻意的设计：
- **用 `> ` 而不是 `- `**：它不是事实陈述，不能混进「每条 bullet 都必须带引用」的统计；
- **不改写、不删除任何 fact**：真机已经证明「分数高的那条反而错」，自动取舍会引入新错误；
- **关键词去停用词后比 token 集合**：`London` 与 `London, England` 不报冲突；
- **员工数留 10% 容差**：避免把四舍五入当冲突。

#### 12.20.4 验证：真实缓存离线回放，0 调用

12 篇真实检索原文（`evals/cache/tavily/`，2026-11-14 那次真实运行的原始返回）分栏目回放：

| 栏目 | 候选 | 保留 | 拒绝 | 理由 |
|---|---|---|---|---|
| company | 3 | 2 | 1 | `notion.online` 域名不一致 + 2014 非多数年 |
| financial | 3 | 2 | 1 | 标题绑定 `0083.KL`，扩展名含 `Berhad` |
| industry | 3 | 3 | 0 | — |
| news | 3 | 3 | 0 | — |

端到端对照（开关 off / on 各跑一遍 `curate`）：

- **off：11 条 References** —— 与真机产物 `evals/live_run.json` 的 11 条一致，证明回放语料就是那次运行；
- **on：9 条 References** —— 恰好少掉 `finance.yahoo.com/quote/0083.KL` 和 `cbinsights.com/company/notion`，
  其余 9 条一条不动。

**这不是「拒得多所以更好」**：真机报告 27 条结论里有 10 条来自 VTec 那篇、4 条来自 notion.online 那篇，
按条数算接近一半的硬伤内容被移除，而真身来源零损失。

#### 12.20.5 验收

| 项 | 结果 |
|---|---|
| 全量测试 | **438 passed**（新增 `tests/test_s10_entity_guard.py` 36 条 + `tests/test_s10_conflict.py` 20 条） |
| 真实缓存回放 | 12 篇 → 拒 2 篇，0 误杀；被拒 url 与 code 逐条断言 |
| A/B 对照 | `entity_guard=off` 时 11 条引用原样回来（含开关 bug 的回归用例） |
| 冲突标注 | 关掉标注后报告 == 开启版去掉 `> ` 行，**逐字相同**（「只加不改」的可执行证明） |
| 依赖 / 额度 | `uv pip check` 103 包兼容；Tavily 仍 **8 / 50**；本轮 **0 调用 0 credits** |

**如实边界**：这次修的是「同名实体混入」与「冲突被抹平」，不改变
`docs/LIVE_SCORE.md` 里 `supported=0 / refuted=2 / not_mentioned=3` 那份判定 ——
那份判定是对**修复前**那份报告做的，保留原样以维持时间线真实。修复后的报告值多少分，
需要重新跑一次真实模型抽取 + judge，归 ②（要 credits）。

### 12.21 S10-B 执行结果：批量真实调研 4 家 + 批量批改 20 条（2026-11-15，10 credits / 20 次模型请求）

对应 ②。用户拍板「3 家，留回退余量」；实际跑成 4 家，因为 Notion 的 4 条 query 全部命中
S8.3 的磁盘缓存（**0 credits**），加进来就有了「同题前后对比」的基准。

#### 12.21.1 新增两个脚本

| 文件 | 作用 | 与旧脚本的关系 |
|---|---|---|
| `evals/batch_live.py` | 吃一串公司，逐家跑完整图，产物 `evals/live_batch.json` | `live_run.py` 是单公司快照，产物不动 |
| `evals/judge_batch.py` | 每家公司一次请求分开批改，产物 `evals/live_score_batch.json` | 复用 `judge.py` 的 prompt / 证据句校验 / `tavily_guard` |

**预算设计**：所有公司共享一个 `CallBudget`。若每家各发一个 `CallBudget(12)`，
4 家就是 48 次调用 = 96 credits。本次上限由算术动态给出：
`min(16, (50 - 已花) // 2)`，重跑多少次都不会越过用户上限。

#### 12.21.2 同一个坑踩了两次：`asyncio.run` 不能放进 for 循环

第二次（`batch_live` v1）第 2 家直接 `RuntimeError: Event loop is closed`，
`AsyncTavilyClient` 的连接池绑在第一个循环上，循环一关就废。修法是整批共用一个事件循环、串行 `await`。

第三次（`judge_batch` v1）犯的是一模一样的错，只是症状换成
`APIConnectionError: Connection error.`，而且更阴——第 1、3 家成功、第 2、4 家失败。
原因是 `ChatOpenAI` 内部的 httpx 连接池同样绑在首个循环上。

**两处都保留失败产物**（`live_batch_v1.json` / `live_score_batch_v1.json`）并计入额度台账：
v1 里 Stripe 的 4 次检索发出去了却没拿到报告、也没写缓存，**那 8 credits 是真实损失，
不能因为「失败了」就不记账**。

#### 12.21.3 结果

| 公司 | 字符 | 引用 | 消歧拒绝 | 判定（支持/反证/未提及） |
|---|---|---|---|---|
| Notion | 3971 | 11 | **4** | **4 / 0 / 1** |
| Figma | 3847 | 12 | 0 | 1 / 1 / 3 |
| Stripe | 4573 | 11 | 0 | 2 / 1 / 2 |
| Airbnb | 4441 | 12 | 0 | 1 / 0 / 4 |
| **合计** | — | — | 4 | **8 / 2 / 10** |

**同题对比（Notion 5 条，同一份 golden）**：修复前 `0 / 2 / 3` → 修复后 `4 / 0 / 1`。
三类硬伤在报告里全部消失：只剩 2013 没有 2014、总部变成旧金山、Financial 从 10 条
VTec 股价变成 2 条真事实。

**补搜验证**：Notion 的 company 栏目被消歧拒掉 1 篇后掉到证据下限，触发 1 次补搜；
候选从 3 篇变 5 篇，那篇 `notion.online` **仍然被判异实体** —— 说明规则不是记住了某个标题。

**2 条 refuted 是 judge 口径偏严，不是系统答错**：Figma 的「2025-07-31 纽交所上市」，
报告写了「July 2025 / FIG」只是缺具体日期与交易所；Stripe 的「双总部」，报告只写了旧金山、
并没有否认都柏林。详见 `docs/LIVE_BATCH.md` §5。

#### 12.21.4 这批数字能说什么、不能说什么

- **能说**：20 条人工核验标准答案第一次全部对上真实报告；0 条未判定、0 条引文造假
  （`quote_check_failed=0` 说明判定有逐字证据支撑）。
- **不能说「准确率 40%」**：`supported_share=0.4` 的分母里有 10 条 `not_mentioned`，
  把它算错得 0.4、排除得 0.8，**两个数都不该叫准确率**。
- **瓶颈已经换了**：修复前是「说错」（实体混淆、自相矛盾），修复后 50% 是「没说」——
  这是检索召回与栏目分配的问题，不是消歧能解决的，要改检索策略、要再花 credits。

#### 12.21.5 验收

| 项 | 结果 |
|---|---|
| 全量测试 | **447 passed**（新增 `tests/test_s10_batch.py` 9 条） |
| 额度 | 本次 **+10 credits**（5 次调用 + 12 次缓存命中），累计 **42 / 50** |
| 模型 | 20 次请求 / 41813 tokens，`max_retries=0` |
| 产物 | `docs/LIVE_BATCH.md`、`evals/live_batch.json`、`evals/live_score_batch.json`（+ 两份 v1 失败留档） |
| 一处自纠 | 两个缓存回放测试原来 `glob("*.json")` 全目录，新增 12 个 Figma/Stripe/Airbnb 缓存后失效 → 改成用 `cache_key()` 精确重算 Notion 那 4 个文件名 |

---

### 12.22 S11 执行结果：按岗位出多版简历措辞（2026-11-15，0 调用 / 0 credits）

#### 12.22.1 核心取舍：只换顺序与解读，不改写事实句

三条正文一律复用 `evals/build_resume.py` 里的 `Bullet.paste` 原文——那句话是出处表锚定过的
（每个数字都是 `{Fxx}` 占位符，渲染时从产物取值）。如果为每个岗位再手写一版措辞，同一件事就有
三种说法，出处表只能管住其中一份，另外两份随时会漂成「没出处的话」。

所以差异化放在三个安全的地方：

1. **先说什么**：按岗位关心的问题重排三条的先后；
2. **说哪三条**：从四条里选与该岗位最相关的三条（一页简历一个项目三条够用）；
3. **为什么有用**：每条配一句岗位视角的解读，可以点代码位置与设计取舍，但不许引入新数字。

护栏 `tests/test_s11_resume_variants.py` 里有一条专门盯这件事：职位版里的每个粘贴行必须
**逐字**出现在 `docs/RESUME.md` 中，改写事实句当场红。

#### 12.22.2 三个方向的排法

| 岗位 | 排序 | 立脚点 |
|---|---|---|
| Agent 工程 | 图编排 → 额度护栏 → 真机排障 | 「为什么必须用图」；护栏证明外部调用不会失控 |
| RAG | 实体消歧/冲突 → 评测台 → 检索工程 | 「检索到错的东西怎么办」「引用能不能核」 |
| 后端 | 额度纪律 → checkpoint/生命周期 → 评测进 CI | 外部依赖失控、进程重启、跑测试会不会花钱 |

合起来四条都用上了；没有哪个方向需要一条不存在的卖点，所以三版都没补新事实。

#### 12.22.3 这一轮顺手修掉的三个问题

1. **D 组漏渲染**：S10-B 新加的 F32–F39 标成了 `group="D"`，但 `render()` 只循环 A/B/C，
   文档里根本没有这张表——14 条测试同时红。修法不是补一行 `§2.4`，而是加 `GROUPS` 登记表，
   §2 分表与 §3 措辞都从它派生；测试改成断言 `f.group in GROUP_IDS`，
   以后新增分组忘了登记会立刻红，而不是静默少一节。
2. **两个数字没有出处**：初版正文写了「0.77 / 0.72」（两篇缓存文档的置信度）和
   「只拒 2 篇、0 误杀」（离线回放的结论），前者是裸数字、后者没有产物文件。
   按红线处理：前者改成「错的那篇 score 反而更高」，后者改成引用 F39 的「触发 N 次拒绝、
   逐篇回放核对全为异实体、无一误杀」。
3. **一处归因不准**：原文写「用 LangGraph 重构公司调研流水线」，看起来像把 LangGraph 引进来。
   查上游 `backend/graph.py` 发现它**本来就是** LangGraph `StateGraph`，只是十个节点一路
   `add_edge` 串到底、没有条件边、没有 `Send`、`compile()` 不带 checkpointer。
   改成「在上游线性 LangGraph 流水线（一路 `add_edge` 串到底、无分支、无 checkpoint）的基础上重构」——
   有基线对照反而更有说服力，也不给面试官留「你到底改了什么」的口子。

#### 12.22.4 验收

| 项 | 结果 |
|---|---|
| 全量测试 | **487 passed**（新增 `tests/test_s11_resume_variants.py` 14 条） |
| 出处表复现 | `--verify` **39 / 39** 条命令通过，含新增 F32–F39 |
| 产物 | `docs/RESUME_VARIANTS.md`、`evals/build_resume_variants.py` |
| 额度 | **0** 次外部连接、**0** 次模型请求、**0** Tavily credits，累计仍 **42 / 50** |
| 边界 | 三版都不写准确率 / 幻觉率 / p95 / 成本单价；仍是 Apache-2.0 二次开发 |

---

### 12.23 S12 执行结果：把存档与台账搬到 Postgres（2026-11-15，0 调用 / 0 credits）

#### 12.23.1 范围：搬两层，留一层

| 要搬的 | 结论 |
|---|---|
| 图的 checkpoint | ✅ 搬（官方 `AsyncPostgresSaver`） |
| 任务台账 + 报告正文 | ✅ 搬（替代上游 Mongo 层，也替代进程内字典） |
| SSE 实时进度 | ❌ 不搬（仍在内存，多 worker 会不一致，如实写进边界） |
| 评测产物 / 检索缓存 / PDF | ❌ 不进库（它们是证据，要能 `git diff`、离线回放、被出处表引用） |

一句话原则：**运行时状态进库，证据留在文件里。**

#### 12.23.2 实现：一套接口，两个后端

- `persistence/checkpointer.py`：`CheckpointSession` 按 `CHECKPOINTER` 选 saver，
  `compile()` / `config_for()` 调用方一行不用改；显式传 `path` 时**强制 SQLite**（测试注入临时文件不被本机 .env 带走）。
- `persistence/job_store.py`：`jobs` + `reports` 两张表，五条语句，连接池 + `dict_row`；
  `update_job` 只认白名单字段，避免拼 SQL 时被注入。
- `persistence/setup_postgres.py`：显式建表（幂等），拒绝「连接时自动建表」——那会把
  「库没准备好」藏起来。
- `persistence/migrate_sqlite_to_pg.py`：用 saver 接口复制，不手工解 msgpack；默认干跑，
  `--apply` 才写，`--force` 才覆盖，逐线程校验三项一致。

#### 12.23.3 三个真坑（都是实测撞出来的）

1. **Windows 的 Proactor 事件循环**：psycopg 异步模式直接拒绝
   `Psycopg cannot use the 'ProactorEventLoop'`。
   uvicorn 0.38 自己传 loop factory（`Server.run()` → `asyncio_run(..., loop_factory=...)`），
   改全局策略对它无效；没开 reload 时它在 Windows 上固定给 Proactor。
   解法：`--loop persistence.pg_compat:selector_loop`，CLI 脚本则在 `asyncio.run()` 前切策略。
2. **自定义 loop 的约定是「调用后返回实例」**：第一版返回 `asyncio.SelectorEventLoop` 类，
   uvicorn 把它当实例用，报 `set_debug() missing 1 required positional argument`。
3. **`.env` 的 `override=True` 让测试写进真实库**：`application.py` 与 `backend/__init__.py`
   都这么写，导致测试里设的 `JOB_STORE=memory` 被覆盖，两次 `TestClient` 用例在真库留下 job 行。
   改成 `override=False`（显式环境变量优先）+ `tests/conftest.py` 里 `setdefault` 两个后端变量，
   复验：跑完两文件后 `select count(*) from jobs` 仍为 0。

#### 12.23.4 验收

| 项 | 结果 |
|---|---|
| 全量测试 | **502 passed**（`tests/test_s12_postgres.py` 13 条，含复查新增 3 条） |
| Postgres 用例覆盖 | 跨会话恢复 / 线程隔离与累加 / 7 节点业务图恢复 / `interrupt`→`resume` / 台账往返 / 白名单拒注入 / 迁移三口径一致 |
| 实测（fixture，0 credits） | 提交 → 台账 `HTTP 200`（旧版 501）→ 报告 200 → **换进程重启**后同一 job 与报告仍可查 |
| 迁移 | SQLite 11 个存档点 → PG 11 个，最新状态逐字段一致 |
| 无库时行为 | 整组用例跳过（不是通过）；`live` 模式下台账连不上直接启动失败，不假装存下来了 |

#### 12.23.5 边界

- SSE 进度仍是单 worker；台账已可跨重启，进度流不行。
- 测试默认 `JOB_STORE=memory` / `CHECKPOINTER=sqlite`，CI 不需要数据库。
- 运行手册见 `docs/POSTGRES.md`；Windows 启动方式以那篇为准。

---

### 12.24 S12 复查：找到 6 处问题，全部修掉（2026-11-15，0 调用 / 0 credits）

复查不是「重跑测试看绿」，而是按「代码 → 边界行为 → 文档一致性」三层过一遍。
测试全绿时下面 5 条依然成立，说明它们是**测试没覆盖到的空档**。

| # | 问题 | 后果 | 修法 |
|---|---|---|---|
| 1 | 完成顺序是先 `status=completed` 再 `store_report` | 存正文失败会留下「状态说完成、报告查不到」的假成功 | 调换顺序：先存正文，再改状态 |
| 2 | `process_research` 的 except 里直接 `await update_job` | 台账写失败会**盖掉真正的报错**，异常还逃出任务变成「never retrieved」 | 包 try/except，失败只记日志，原始错误保留 |
| 3 | 端点先写内存再写库，库写失败时内存那条留着 | 库和内存各说一套，查库 404、SSE 却看得见 | `create_job` 失败时 `job_status.pop(job_id)` 再抛出 |
| 4 | `_looks_like_missing_schema` 只做字符串匹配 | `database "x" does not exist` 被误判成「表没建」，提示跑错命令 | 先判 `psycopg.errors.UndefinedTable`，再要求报文含 `relation` |
| 5 | 忘了建表时只在**第一个请求**报错 | 启动看着正常，请求时才 500，排查绕远 | 启动时 `missing_tables()` 探一次：fixture 退回内存并告警，live 直接启动失败 |
| 6 | `CheckpointSession(backend=...)` 不校验取值 | 写成 `mysql` 会落到 else 分支去连 Postgres，报错牛头不对马嘴 | 只接受 `sqlite` / `postgres`，其余当场 ValueError |

顺带两处小修：迁移校验增加 `next_equal`（值对但 next 不同 = 迁了个不能续跑的存档）；
README 里 `POSTGRES_DSN` 的状态列原来复用 `No*`，与「LLM key 必须有一个」的脚注语义冲突，改成 `No†` 并补脚注。

新增 3 条护栏：后端名非法要报错、缺少表的探测不能误伤「库不存在」、空库要能点名缺哪两张表（用临时数据库建/删验证）。

**回归**：全量 **502 passed**；迁移用更严口径重跑，`11 -> 11，最新状态一致=True，下一步一致=True`。

---

### 12.25 UI 首次真正启动：Tailwind 版本自相矛盾（2026-11-15，0 调用 / 0 credits）

第一次把前端跑起来（`npm install && npm run dev`）就撞到 Vite 报错遮罩：

```
[plugin:vite:css] [postcss] It looks like you're trying to use `tailwindcss` directly
as a PostCSS plugin. The PostCSS plugin has moved to a separate package ...
```

**根因是上游自己矛盾**：`ui/package.json` 写的是 `tailwindcss ^4.3.3`，但
`ui/src/index.css` 用的是 v3 指令（`@tailwind base/components/utilities`）、
`postcss.config.js` 也是 v3 写法（`tailwindcss: {}`）、`tailwind.config.js` 用 JS 配置扩展主题。
三处都是 v3，只有依赖号是 v4 —— 这套前端在原始状态下根本跑不起来。

**修法**：按代码实际写法把依赖钉到 v3（`tailwindcss@^3.4.17`），不动 CSS 与 config。
备选是迁到 v4（装 `@tailwindcss/postcss` + 改 `@import "tailwindcss"` + `@config` 接 JS 主题），
但 v4 改了默认边框/ring 等表现，为一个上游 UI 承担视觉回归不值得。

**验证**：`npm run build` 通过（1773 modules，CSS 35.91 kB / JS 532.91 kB，tsc 无错）；
dev server 下 `/src/index.css` 返回 50 KB 编译结果、`.flex`/`.text-` 等工具类正常生成、
字体 200。这类问题用 `curl` 看首页 200 是查不出来的——**首页永远是 200，错在样式编译**。

---

### 12.26 前后端联合复查：5 处契约不符（2026-11-15，0 调用 / 0 credits）

检查方式不是"再跑一遍测试"，而是三张清单对齐：
**后端 openapi 里的真实路由** × **前端所有 fetch/EventSource 调用点** × **每个接口手工打一遍**。

| # | 问题 | 现象 | 修法 |
|---|---|---|---|
| 1 | 空公司名返回 200 | `{"company": ""}` 会真的跑一次空调研，还在台账留记录 | `ResearchRequest.company` 加 `min_length=1` + 去空白校验，空白返回 **422** |
| 2 | `/api/health` 一直是 404 | 后端日志被探活请求刷了几十条 | 同时注册 `/health` 与 `/api/health` 两个路由指向同一函数 |
| 3 | 前端进度映射是**上游旧节点名** | 新图节点是 grounding/research/curate/evidence_check…，旧映射表写的是 financial_analyst/curator/editor，界面上会直接显示 `Processing evidence_check...`，阶段条也不推进 | 按新图重写 `stepMap` 与阶段数组，提示语改用友好名 |
| 4 | `complete` 事件不推阶段 | 拒答/降级的运行走不到 briefing，而报告面板只在 `briefing\|complete` 显示 → **报告不出来** | 收到 `complete` 时 `setCurrentPhase('complete')` |
| 5 | `/research/{id}/report` 有一行 `raise` 之后的 `return report` | 不可达代码，读代码时误导 | 删除 |

**确认没问题的地方**（都实测了，不是看代码猜）：
CORS 预检回显 `http://localhost:5174`；`/generate-pdf` 返回 `application/pdf`（1783 字节，可被前端 `blob()` 接住）；
`/research/pdf/xxx` 不会被 `/research/{job_id}` 抢先匹配（返回 404 而不是 404 job）；
`/config` 与 `/models` 的字段和前端 `ServerConfig` / `ModelInfo` 接口一致；
SSE 的 `complete` / `error` 两条分支都会 `eventSource.close()`，不会无限重连。

**另外发现一件环境问题**：后端进程在两次对话之间被杀（退出码 127，日志无异常堆栈），
不是代码问题；重启即可。SSE 实测序列为 `grounding → evidence_check → complete`——
fixture 太快，中间节点在一次 0.1s 轮询内就跳过了，界面上会看到跳步，这是预期行为。

**遗留（属于产品决策，没动）**：界面上的行业/总部/模型/key 四个字段后端不消费；
模型下拉来自 OpenRouter 而新图用 DashScope；无鉴权 + CORS 全开。这三条要改就动 UX 或部署姿势，得先定。

**回归**：全量 **505 passed**；前端 `npm run build` 通过（4.16s，tsc 无错）。

---

### 12.27 「要几个 key 才能用」：0 个，但前端不让点（2026-11-15，0 调用 / 0 credits）

实测把前端跑起来后，点提交会被弹设置框挡住。查下来是上游的判定过严：

```ts
const hasLlmProvider = ... ;                       // 只认 OpenRouter / OpenAI
const needsLlmSetup = serverConfig !== null && !hasLlmProvider;
if (needsLlmSetup) { setIsSettingsOpen(true); return; }   // 直接不提交
```

它不知道这个 fork 有 **fixture 模式**（本地固定语料 + 确定性 stub，0 key 可跑），
也不知道本项目 live 走的是 **DashScope** 而不是 OpenRouter。

修法：
- 后端 `/config` 增加 `app_mode`、`requires_llm_key`、`dashscope_configured`、`tavily_configured`；
- 前端 `needsLlmSetup` 改成 `serverConfig?.requires_llm_key === true && !hasLlmProvider`；
- `hasLlmProvider` 增加 `dashscope_configured`。

**key 矩阵（如实）**

| 模式 | 需要几个 key | 是哪些 |
|---|---|---|
| `fixture`（当前默认） | **0** | 无 |
| `live` | **2** | `TAVILY_API_KEY`（检索）+ 一个模型 key：`DASHSCOPE_API_KEY`（qwen-plus）/ `OPENROUTER_API_KEY` / `OPENAI_API_KEY` 三选一 |

**重要边界**：界面上的 key 输入框是摆饰——`process_research` 只从环境变量解析凭据，
不读请求体里的 `tavily_api_key` / `openrouter_api_key`（避免密钥进日志）。所以填了也没用。

**回归**：506 passed；前端 build 通过；`/config` 实测返回
`app_mode=fixture, requires_llm_key=false, tavily_configured=true`。

---

### 12.28 「搜别的公司搜不到」：不是坏，是演示语料只覆盖一家（2026-11-15）

#### 12.28.1 根因（代码级）

`capabilities/retrieval.py` 的 fixture store 按公司名精确匹配：

```python
def find_case(self, company: str) -> dict | None:
    for case in self.cases.values():
        if case["company"].lower() == company.lower():
            return case
    return None
```

`evals/fixtures/tavily_responses.json` 里只有一家公司的语料（`sufficient` 场景）。
所以 Tesla / Figma / 任意公司都拿到 **0 篇文档** → 四个栏目都判「证据不足」→ `degrade`
输出「该类信息未找到公开依据」。

**这是拒答机制在正常工作**，不是搜索坏了；只是演示模式没有那家公司的数据。

实测（同一份 fixture store）：

| 公司 | company | industry | financial | news |
|---|---|---|---|---|
| Notion | 2 | 2 | 2 | 2 |
| Tesla | 0 | 0 | 0 | 0 |

#### 12.28.2 让「任何公司都能搜」：默认切 live

- 新增 `run_server.py` 统一入口：Windows 事件循环用 `selector_loop`；把系统变量
  `SYSTEM_ALIYUN_APIKEY` 映射成 `DASHSCOPE_API_KEY`（仅进程内，不落盘、不进 git）；
  `--fixture` 可随时退回演示模式。
- `.env` 默认改为 `APP_MODE=live` + `TAVILY_LIVE_ENABLED=true` + `TAVILY_MAX_CALLS=16`。
- `retrieval.queries_per_analyst / max_results_per_query / search_depth` 支持环境变量覆盖
  （此前只有它们三个写死，其余配置都可覆盖，不一致）。

#### 12.28.3 两家新公司的真实结果（这就是"正常跑"的样子）

| 公司 | 参数 | 检索 | 花费 | 结果 |
|---|---|---|---|---|
| Tesla | 每栏 1 query、上限 4 次 | 4 次（全为新检索） | **8 credits** | 6528 字，四栏 27/10/6/3 条，12 个引用 |
| Figma | 默认（每栏 2 query、上限 16） | 8 条 query **全部命中缓存** | **0 credits** | 5133 字，四栏 19/6/5/4 条，12 个引用 |

Figma 那次证明：**同一家公司重复跑不花钱**（缓存 key 由 query + 参数取 sha256，命中不扣额度）。

#### 12.28.4 额度与台账

用户 2026-11-15 把放行上限从 50 放宽到 200；台账 `ceiling` 改为 200，累计 **50**（Tesla +8，Figma +0）。
顺带修掉一处"双真相"：`batch_live` 原来读 `live_run.USER_CREDIT_CEILING`（S8 时点冻结的 50），
现在读台账 `ceiling`，代码里不再留会漂移的常数。

#### 12.28.5 一个被这次改动炸出来的测试问题

`.env` 改成 live 后，**506 条测试里 50 条失败、7 条报错**：所有走 `get_settings()` 的用例
都读到了 `.env` 的 `APP_MODE=live`，开始找 key、连真实服务。
修法：`tests/conftest.py` 用 `setdefault` 把 `APP_MODE=fixture`、`TAVILY_LIVE_ENABLED=false`、
`TAVILY_MAX_CALLS=0` 一起钉死——测试永远离线。

**回归**：全量 **506 passed**；`--verify` 39/39；两份真实报告存进 `docs/samples/`。

---

### 12.29 内容太短 & 输出英文：两个独立问题，分别修（2026-11-15）

#### 12.29.1 「内容少」跟积分的真实关系

- **检索按次数计费**，不按返回条数：`advanced` 每次 2 credits，每条 query 抓几条结果都是这个价。
- 所以「每条 query 多抓几篇」是**免费**的，只增加 token；「多生成几条 query」才多花 credits。
- 原默认 `max_results_per_query=3`（每栏 2 query → 最多 6 篇素材），已改为 **5**（最多 10 篇）。
- 报告长度还取决于抽取规则：原来没要求「不合并事实」，模型会把多条信息压成一句；
  现在明确要求「不同时间/数字/主体分别成条，保留具体数字与型号」。

对比（同一家英伟达，各栏条数）：

| | 公司 | 行业 | 财务 | 新闻 | 合计 | 引用 |
|---|---|---|---|---|---|---|
| 改前（3 篇/query，英文） | — | — | — | — | 约 34 条 | 12 |
| 改后（5 篇/query，中文） | 21 | 13 | 20 | 14 | **68 条** | 20 |

#### 12.29.2 「输出英文」：三层约束才压得住

第一次只在 system prompt 里写「所有 claim 用简体中文」，结果**没用**——20 篇英文长文档一压，
qwen-plus 照抄来源语言。最终三处一起加才生效：

1. `Fact.claim` 的 **Pydantic 字段描述**（function_calling 会把 schema 一起送给模型，最有效）；
2. **payload 里显式一行** `output_language: 简体中文`，紧挨着文档，比远处的一句要求管用；
3. system prompt 结尾再强调一次。

配套把标题与四个栏目标题也中文化（`# {company} 研究报告` / 公司概况 / 行业概况 / 财务概况 / 新闻动态）。
`## References` **保持英文**——`evals/judge.py`、`evals/live_quality.py` 都按这行切分正文与来源清单，
改它就要同步改评测链，风险大于收益。

#### 12.29.3 连带修的两处

- **缓存回放测试会静默跳过**：改 `max_results` 后 cache key 全变，`test_s10_entity_guard` 的两条回放找不到
  旧文件就 skip 了。改成用**抓取时**的参数（`CAPTURE_MAX_RESULTS = 3`）重算 key，回放才名副其实。
- **报告长度断言 822 → 772**：标题中文化后 fixture 报告变短，5 处硬编码同步更新。

#### 12.29.4 花费

| 运行 | 检索 | credits |
|---|---|---|
| 英伟达首次（改 max_results 后抓取 + 4 条补搜） | 12 次 | **24** |
| 英伟达重放（提示词生效后验证中文） | 0（全部命中缓存） | **0** |

台账累计 **74 / 200**。

**回归**：全量 **506 passed**（含 2 条缓存回放，不再跳过）；中文样本见 `docs/samples/nvidia_live_report_zh.md`。

---

### 12.30 历史数据：存了，但之前看不见（2026-11-15，0 调用 / 0 credits）

#### 12.30.1 已经存了什么

`JOB_STORE=postgres` 时，每次调研都会落两行：

- `jobs`：公司名、状态、当前节点、错误、入参、创建/更新时间；
- `reports`：报告正文（Markdown 全文），与 `jobs` 一对一（外键级联删除）。

实测库里当时有 **19 条任务 / 17 份报告**，包括 Meta、英伟达（两版）、Nvidia、Figma、Tesla、Notion 等。

#### 12.30.2 缺的那一环：没有浏览入口

历史只能凭 `job_id` 单条查（`GET /research/{job_id}`），而 `job_id` 是前端 POST 之后才拿到的——
刷新页面就断了。等于**数据在库里睡着**。

补的接口：

```
GET /research?limit=20&company=figma
```

返回 `{source, jobs:[{job_id, company, status, current_step, error, created_at, updated_at, has_report, report_chars}]}`。
`company` 用 `ilike` 模糊匹配（库里同时存在 `Nvidia` 和 `英伟达`，等值匹配会漏）；
`has_report` / `report_chars` 让人一眼分清「跑完有报告」和「只有一条状态」。

内存模式（`JOB_STORE=memory`）也实现了同一接口，从 `job_status` 里现拼，字段保持一致。

#### 12.30.3 顺带发现的两种脏数据（如实记录，暂不清理）

| 记录 | 现象 | 原因 |
|---|---|---|
| `字节跳动` / `pending` | 永远停在 pending，没有报告 | 提交后进程被杀，没有「僵尸任务回收」 |
| `Tesla` / 174 字报告 | 四栏全是拒答话术 | 当时还在 fixture 模式，语料里没有 Tesla |

这两条恰好把之前写在文档里的两个边界变成了实物证据：**没有 reaper**、**fixture 只认内置公司**。

#### 12.30.4 仍未做

- **UI 没有历史面板**：接口有了，前端还没画列表；现在是 `curl` 能看到、点不到。
- **同一家公司多次运行是并列记录**，没有「每家公司只看最新一份」的视图。
- **没有删除/归档接口**，测试数据只能进 psql 清。

**回归**：全量 **509 passed**（新增 `tests/test_s5_entrypoints.py::test_history_endpoint_lists_runs_and_filters_by_company`）。

---

### 12.31 数据目录从命名卷迁到 E 盘：搬完了，但顺带修了两个真 bug（2026-11-15）

#### 12.31.1 迁移时发现的状态

容器 `pj-pg` 已经改成挂载 `E:/DockerData/postgresql/pgdata`，但那个目录里是**全新的空库**
（`Did not find any relations`）——盘换了、数据没搬。19 条任务 / 17 份报告 / 358 个存档点
还在旧命名卷 `pj-pg-data`（67M）里。

**做法**（物理搬运，版本完全一致，比 dump/restore 更保真）：

1. 先把旧卷打包到 `E:/DockerData/postgresql/pgdata-old-volume-20261115-1816.tgz`（13M）；
2. 停容器 → 清空目标目录（`find /to -mindepth 1 -delete`，不动挂载点本身）→ `cp -a /from/. /to/`；
3. 启动容器，核对：**19 / 17 / 358，与迁移前完全一致**。

绑定挂载的属主是 999:999（容器内 postgres），所以没有踩到
`data directory has wrong ownership` 这个经典坑。

#### 12.31.2 Bug 1：`localhost` 走了 IPv6，连接池 30 秒起不来

迁完之后服务直接起不来：

```
psycopg_pool.PoolTimeout: pool initialization incomplete after 30.0 sec
```

单条连接能成功但**要 8.24 秒**；换 `127.0.0.1` 只要 **0.18 秒**。
原因：Windows 上 `localhost` 先解析到 `::1`，该地址不通再回退 IPv4，每次白等约 8 秒；
连接池默认 `min_size=4`，4×8=32 秒 > 30 秒初始化预算，于是必然超时。

修法：`.env` / `.env.example` / 文档统一改 `127.0.0.1`；池参数改成
`min_size=1, max_size=8, timeout=10`（起步只要一条连接，连不上就早点报错）。

#### 12.31.3 Bug 2：Postgres 重启后，池里的坏连接让接口 500

迁移过程中重启了数据库，后端没重启，`GET /research` 直接 500：

```
psycopg.OperationalError: consuming input failed: could not receive data from server
```

psycopg_pool 会在归还时丢弃坏连接，但**第一次拿到它的请求仍然会抛**。
修法：`persistence/job_store.py` 加 `_retry_once()`，所有读写遇到 `OperationalError`
重试一次（并给池子 50ms 丢弃坏连接）；真连不上时只试两次，不会把请求挂死。

**验证**：后端不重启，`docker restart pj-pg` → 等 healthy → 再打 `GET /research`，
**HTTP 200、返回 3 条**。这条也顺带证明了绑定挂载的数据是持久的。

#### 12.31.4 迁移后的状态

| 项 | 值 |
|---|---|
| 数据目录 | `E:/DockerData/postgresql/pgdata`（67M，属主 999:999） |
| 行数 | jobs 19 / reports 17 / checkpoints 358 |
| compose | 已改为 bind mount，注释里写明属主与目录要求 |
| 回滚点 | 旧卷 `pj-pg-data` + `pgdata-old-volume-20261115-1816.tgz` |

**回归**：全量 **511 passed**（新增 `_retry_once` 的两条用例）。

---

### 12.32 一个从没被读过的配置项：`queries_per_analyst`（2026-11-15）

#### 12.32.1 发现

跑字节跳动时看日志，每轮只有 **4 次**检索（每栏 1 条），但配置写的是
`queries_per_analyst: 2`。全仓 grep 确认：

```
config/loader.py:101        queries_per_analyst: int = Field(ge=1)   # 只是解析
tests/test_config_loader.py 断言它等于 2                              # 只是断言
```

**生产代码里没有任何地方读它。** 也就是说这个旋钮从 S3 起就是死的。

#### 12.32.2 更正之前的说法

12.28 / 12.29 里我写过「每栏 2 条 query、最多 8 次检索 / 16 credits」——**错了**。
实际从流程到计费一直是「每栏 1 条、每轮 4 次检索、8 credits」。抱歉。

#### 12.32.3 修法：接上，但默认保持 1

- `build_live_query()` 增加 `variant` 参数：同一栏的第 N 条 query 追加 `variant N`。
  措辞必须稳定，否则缓存 key 每变一次，同一家公司就要重新花钱。
- `fetch_company_documents()` 按 `queries_per_analyst` 循环发 N 条，结果按 URL 去重合并。
- 默认值从 2 改成 **1**：接上之后如果还留 2，等于**悄悄把每轮花费翻倍**（8 次 / 16 credits）。
  想要更多素材再显式设 `QUERIES_PER_ANALYST=2`。

#### 12.32.4 字节跳动实测（这就是「输公司名会怎样」的答案）

| 项 | 值 |
|---|---|
| 输入 | `字节跳动`（另有一次 `字节跳动·`，尾随符号不影响检索） |
| 检索 | 4 次（每栏 1 条，每条 5 篇） |
| 花费 | **8 credits** |
| 结果 | 5952 字，四栏 **19 / 11 / 7 / 8** 条，16 个引用 |
| 来源 | bytedance.com、wikipedia、linkedin、rocketreach 等 |

内容确实在讲字节跳动：2012 年由张一鸣/梁汝波创立、2016 年抖音、2017 年 TikTok、
收购 Musical.ly、15 万员工、TikTok/CapCut/Lark/Pico 等产品线。
**私企的财务栏天生偏薄**（7 条），因为没有公开财报——这是检索现实，不是 bug。

**回归**：全量 **512 passed**（新增 `test_queries_per_analyst_is_actually_honoured`）。

---

### 12.33 前端瘦身：13 个组件砍到 5 个（2026-11-15，0 调用 / 0 credits）

#### 12.33.1 砍的依据不是「看着乱」，是「后端不会发生」

把三张清单对齐：**后端 SSE 实际发什么事件** × **前端监听了什么事件** × **请求体里哪个字段真被消费**。

后端 `event_generator()` 只发三种：

```
{"type": "progress", "step": "<node>"}
{"type": "complete", "report": "..."}
{"type": "error",    "error": "..."}
```

前端却写了 13 种事件的处理器：`query_generating`、`query_generated`、`research_init`、
`crawl_start`、`curation`、`enrichment`、`briefing_start`、`briefing_complete`、
`report_compilation`、`report_chunk`……这些**新图一个都不会发**。所以三个面板永远不显示：

| 组件 | 行数 | 只在哪些事件里渲染 |
|---|---|---|
| `ResearchQueries` | 86 | `query_generating` / `query_generated` |
| `CurationExtraction` | 86 | `curation` / `enrichment` |
| `ResearchBriefings` | 92 | `briefing_start` / `briefing_complete` |

同理 `process_research` 的 docstring 早就写明「只消费 `company`」，但界面上还有
Tavily key（必填！）、Company URL、HQ、Industry 四栏，以及一个模型选择器。

#### 12.33.2 删掉的东西

| 删的 | 行数 | 为什么 |
|---|---|---|
| Tavily API Key 输入框（**必填**） | ~40 | 后端只从环境变量读 key；不填它按钮就禁用，填了也没人读 |
| Company URL / HQ / Industry | ~80 | 同上，请求体里这三个字段从未被消费 |
| `LocationInput`（地图自动补全） | 248 | 只服务于被删的 HQ 栏；连带 `@types/google.maps`、`VITE_GOOGLE_MAPS_API_KEY` |
| `SettingsPanel`+`ModelSelector`+`ModelLogo`+`models.ts`+`settings.ts` | 191+189+23+95+50 | 模型选择不生效（后端用 `LLM_MODEL=qwen-plus`），`/models` 拉的是 OpenRouter 目录，两套配置对不上 |
| `ResearchQueries`/`CurationExtraction`/`ResearchBriefings` | 86+86+92 | 事件永远不会发出 |
| `useSmoothText`（打字机） | 98 | 报告整篇一次到达，没有 chunk 可「平滑」 |
| App.tsx 里 13 条事件分支 + 6 个状态字段 | ~300 | 同上 |
| footer 的「Search API docs」 | 5 | 上游品牌链接，与本项目无关 |

顺手把 `rehype-raw` 去掉了（报告是 Markdown，不需要解析原始 HTML，少一个 XSS 面）。

#### 12.33.3 留下的（用户点名要保留）

- **背景图**（`tavily-landscape.webp` + 上下渐隐）原样保留；
- **首页那排默认公司**（24 个 chip）原样保留，点一下直接开跑。

#### 12.33.4 换来的数字

| | 之前 | 之后 |
|---|---|---|
| 前端源码 | 约 **3300 行**（13 组件 + 3 模块 + 1 hook） | **560 行**（App + 5 组件 + types） |
| `index.css` | 278 行 | 145 行 |
| 生产 JS | 532.91 kB | **305.99 kB** |
| 生产 CSS | 35.91 kB | **15.99 kB** |
| 页面区块 | 标题 + key + 4 字段 + 按钮 + chips + queries + curation + briefings + 报告 + footer | 标题 + 1 字段 + 按钮 + chips + 状态 + 报告 |

另外两处产品决定：

1. **界面文案改中文**。报告从 12.29 起就是中文，界面原来还是英文壳；顺手把
   `index.html` 的 `lang` 也从 `en` 改成 `zh-CN`。
2. **右上角加一个只读模式标签**：`真实调研` / `演示数据`。这直接解决 12.28 那次
   「我搜别的公司为什么没结果」——现在一眼能看到自己是不是在演示模式。

#### 12.33.5 实测（不是只看构建通过）

用 Edge headless + CDP 真点了一遍（脚本临时写在 `.tmp_probe/`，用完删除）：

| 步骤 | 结果 |
|---|---|
| 首屏 | 标题「公司调研助手」、**24 个 chip**、页面高 1103px |
| 填「字节跳动」 | 按钮从 disabled → 可点 |
| 点击 | SSE 跑通，报告出现 |
| 报告结构 | **5622 字符 / 5 个 h2（公司概况·行业概况·财务概况·新闻动态·References）/ 39 条 bullet / 16 个链接** |
| 页面高度 | 3635px |
| 控制台 | `console.error` 与 `exceptionThrown` **全程为空** |
| 花费 | **0 credits**：台账仍 90/200，最近 30 分钟新增缓存文件 **0** 个（同一家公司全部命中磁盘缓存） |

`static/app-screenshot.png` 也换成了新界面截图——README 里那张一直是旧 UI。

#### 12.33.6 顺手纠正的 README 失真

1. 「Runs on any model … pick it from the in-app Settings」→ 界面已经没有模型选择；
2. 「`GET /models` … when the UI opens the model picker」→ UI 不再调用，路由保留但没人用；
3. 「Google Maps — upstream UI feature only」→ 已随 HQ 栏删除。

**回归**：前端 `npm run build` 通过（1708 modules，tsc 无错）；后端 `pytest` **512 passed**（与改造前一致）。
`npm run lint` 跑不起来——`eslint.config.js` 依赖未安装的 `typescript-eslint`，属上游遗留，本轮未修（`tsc` 已经是真正的类型闸门）。
