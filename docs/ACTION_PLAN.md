# 行动方案：按步执行清单

> 本文把任务清单 #1–#9 转成「一步一验收」的执行序列。每完成一步，更新状态并留下可查的产出物。
> 制定日期：2026-11-14 | 设计依据：`docs/PROJECT_PLAN.md`、`AGENT.md`

---

## 0. 环境事实（已实测，不是假设）

| 项 | 实测结果 | 对执行的影响 |
|---|---|---|
| Python | WorkBuddy 内置 3.13.14 / `D:\Python\Python311` 等 4 个解释器 | 用 3.11 建独立 venv，兼容性最好 |
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
| **S2** | #2 状态契约 | `StateGraph(ResearchState)` + `add_messages` / `merge_docs` reducer；`compile(checkpointer=...)` 接真实 SQLite Saver；`thread_id` 按模板 | `persistence/`、`graph/state.py`、单元测试 | 进程重启后同一 thread 可恢复；并行写回不覆盖；恢复前后 State 一致 | ⏳ |
| **S3** | #3 自纠正回路 | `evidence_check` 判定 + `add_conditional_edges` + `retry_count<=2` + `degrade` 降级拒答 | `graph/conditions.py`、`graph/nodes/degrade.py`、3 类 fixture 用例 | sparse 样本触发回退并在 2 轮内收敛；empty 样本输出「无公开依据」且不编造 | ⏳ |
| **S4** | #4 并行与子图 | 去掉节点内 `asyncio.gather`，改 LangGraph 并行边 / `Send`，4 analyst 收成 `research_subgraph` | `graph/subgraphs/`、白板图 | 主图 6–7 节点，可完整画出；reducer 合并可验证 | ⏳ |
| **S5** | #5 LangChain 深化 | Tavily 封 `BaseRetriever`；`with_structured_output` + 字段置信度 + 校验重试；行内引用 | `capabilities/`、Pydantic schema | 每条 Fact 能对回 source_url；抽取失败自动重试不静默丢字段 | ⏳ |
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
| venv | Python 3.11.9 独立环境；官方 PyPI 源装齐 99 个包并导出 `requirements.lock.txt`；清华镜像不可用（已记录） |
| YAML | 两份配置 `yaml.safe_load` 全量通过，阶段 0 欠账解除 |
| 图对象 | 真实 `compile()` 成功；**12 节点 / 14 边 / 0 条件边 / 无 checkpointer**，与静态核查一致 |
| 纯节点 | grounding / collector / curator 真跑成功；阈值 0.4 过滤行为与引用数可复现 |
| 新发现缺陷 | `typing.TypedDict` + Python 3.11 + pydantic 2.14 导致 `get_input_schema()` 抛 `PydanticUserError` → S2 改用 `typing_extensions.TypedDict` 并补 schema 用例 |

完整证据见 `docs/BASELINE.md` 与 `baseline/upstream_graph.json`。

---

## 3. 全局纪律（每一步都检查）

- 「跑通」= 真实执行代码并拿到输出；静态检查只能作为补充，不得冒充实测。
- 指标数字只能由 `evals/run_eval.py` 产出；未跑出的数字一律写 `X`。
- 每个技术结论都要能指到具体文件与行号 / commit。
- 每次完成一步：更新任务状态 → 写工作区记忆日志 → 再进入下一步。
- 遇到环境阻塞（缺 key、装不上包）如实记录，不静默降级、不编造结果。
