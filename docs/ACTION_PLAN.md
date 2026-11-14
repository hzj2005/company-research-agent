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
| **S5** | #5 LangChain 深化 | Tavily 封 `BaseRetriever`；`with_structured_output` + 字段置信度 + 校验重试；行内引用 | `capabilities/`、Pydantic schema | 每条 Fact 能对回 source_url；抽取失败自动重试不静默丢字段 | 🔄 进行中（8.1 已完成，见第 8.7 节；计划见第 8 节） |
| **S6** | #6 HITL | 成稿前 `interrupt()` 复核 + `Command(resume=...)`；复核留痕导出标注 | `graph/nodes/human_review.py` | 中断→恢复后 State 一致；依赖真实 checkpointer | ⏳ |
| **S7** | #7 评测台 | golden set（30–50 公司 × 5 事实）、8 项指标、4 组 A/B、scorecard、CI | `evals/`、`.github/workflows/eval.yml` | 一条命令出分，能定位退化用例 | ⏳ |
| **S8** | #8 真实实测 | **需 key**。切 `APP_MODE=live`，真实模型 + 真实 Tavily + 真实 DB 跑全量 | 对比表、失败案例、成本/延迟取舍 | 每个数字能由脚本与日志当场复现 | ⏳ 阻塞：等 key |
| **S9** | #9 简历交付 | 3–4 条描述 + 面试追问清单 | `docs/RESUME.md` | 每条能指到具体文件与 commit | ⏳ |

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

| 项 | 现状 | 归属 |
|---|---|---|
| **对外入口仍跑原版图** | `langgraph_entry.py:4`、`application.py:115` 仍指向 `backend.graph.Graph`；新图只能靠 CLI 跑。规划里原本就没排「接线」这一步 | **用户拍板：等 S5 接真实 LLM/Tavily 后一次切换**，避免 API 现在返回合成报告显得一眼假 |
| `evidence_check` 只数篇数、不验内容 | `graph/nodes/decide.py:31–37` 判定是「每栏目合格文档 ≥ 2」；empty 报告里「该领域缺少公开规模数据」也带 `[n]` | S7 的 `citation_traceability`（来源确实支持 claim）需要 judge / golden set，S3 无实现手段 |
| `any(retry_count >= max_retry)` 整体降级 | `graph/conditions.py:45`：一个栏目达上限会连累其他栏目 | S4 拆子图时一并改成栏目级降级 |
| `degrade.enabled=false` 仍置 `degraded=True` | `graph/nodes/decide.py:78–97`，只影响措辞 | S4 明确该配置语义或删除 |
| `curated_data` 按 URL 累积 | `merge_docs` 无法移除上一轮已失效引用 | S4 配合子图重算 |
| `features.structured_output` / `human_review` | 已可环境变量覆盖，但代码尚未消费 | S5 / S6 生效 |

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

- 仍是 fixture 模板简报，不接真实 LLM / Tavily（S5）；对外入口仍指原版图（用户拍板 S5 再切）；内容级 `citation_traceability` 仍归 S7。
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

**S4 如实边界**：仍是 fixture 模板简报；对外入口仍指原版图（S5 再切）；内容级 `citation_traceability` 仍归 S7。

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
