# S8.0 / S8.1 真实实测准备度报告

> 生成日期：2026-11-14（S8.0/S8.1）；同日晚补充 S8.2 实测（**第 8 节**）与 S8.3 端到端实测。
> **第 1–8 节是当时的历史快照，保留不改**：其中的「0 次真实调用」「真实返回结构未实测」
> 描述的都是各节写成时的状态，不要当成当前状态引用。
>
> **当前累计**：**4 次真实 Tavily 调用**（8 credits）、**5 次真实模型请求**（qwen-plus）。
> S8.3 的完整数字、真实失败案例与如实边界见 **`docs/LIVE_FINDINGS.md`**。
> 密钥只在实调运行时从用户级变量映射进进程内存，未打印、未落盘、未提交。
> 用户 2026-11-14 21:20 拍板：模型用阿里云百炼 `qwen-plus`、Tavily 放行 2–20 credits、
> 真实 golden 由助手查 5 家×5 条候选后交用户人工复核（详见第 6 节末）。

---

## 1. 凭据与运行模式体检（只报存在性，不报值）

本轮所有检查都在**当前进程**里做，读的是进程环境，不是 Windows 用户级变量。

| 变量 | 当前进程 | 说明 |
|---|---|---|
| `APP_MODE` | absent | 走配置默认 `fixture` |
| `TAVILY_API_KEY` | absent | 用户此前说明设在「用户变量」里；Windows 下需重启终端/IDE 才会被新进程继承。`config/loader.py:200` 明确读不到时抛 `MissingTavilyCredentials`，不静默回退 |
| `OPENROUTER_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY` | 全部 absent | live 简报后端构造需要其一 |
| `TAVILY_LIVE_ENABLED` / `TAVILY_MAX_CALLS` / `TAVILY_DRY_RUN` | 全部 absent | 走配置默认值 |

**结论：当前进程不具备发起真实调用的条件**，这正是额度护栏期望的状态。
本轮**没有**去注册表/用户变量里把 key 取出来，也没有要求用户提供明文 key。

## 2. 密钥泄露面检查

| 检查 | 结果 |
|---|---|
| `.env` 文件 | 不存在（模板 `.env.example` 已入库，无真实值） |
| `.gitignore` | 覆盖 `.env`、`data/`、`*.db`、`evals/cache/`、`.venv/` |
| `git ls-files` 含 secret 文件 | 无 |
| `Settings` / `LLMCredentials` / `TavilyCredentials` | 凭据刻意不进 `Settings`（避免 `model_dump()` / 日志带出），用 `SecretStr` 包装 |
| `code_sha256` / scorecard | 不含密钥 |

## 3. live 三重 opt-in 与 dry-run 路径

静态核对 `capabilities/retrieval.py:make_document_tool` 与 `config/settings.yaml`：

- 真实调用需 `APP_MODE=live` + `TAVILY_LIVE_ENABLED=true` + `TAVILY_MAX_CALLS>0` **三者同时满足**，默认 `false / 0 / false`。
- `APP_MODE=fixture` 是第一道闸：即使误开 live 开关，也只读本地 fixture（`tests/test_s5_retriever.py` 有反向验证）。
- 预算是 `CallBudget` 进程内计数，用尽抛 `TavilyBudgetExceeded`，不重试；缓存命中不扣额度。

**本阶段修复的真实缺陷**：原实现里 `TAVILY_DRY_RUN=true` 仍会无条件调用
`resolve_tavily_credentials()`，无 key 时直接抛错，导致 `.env.example` 承诺的
「先看会发哪些 query」根本跑不通（探针实测：`MissingTavilyCredentials`）。
现改为：dry-run 是**独立 0 请求路径** —— 不需要 key、不需要放行额度、
不构造 `AsyncTavilyClient`，强制使用 `DryRunSentinel`；并加了预算一致性校验
（`CallBudget` 必须是 `dry_run=True`），防止配置被误改后拿真实预算跑预演。
三重 opt-in 对**真实调用**的约束一点没放松。

## 4. 上游出网风险与 SDK 静态签名

| 项 | 结论 | 位置 |
|---|---|---|
| 上游 `/models` 端点 | `httpx.AsyncClient` GET `https://openrouter.ai/api/v1/models`，**会出网**（有 1h 缓存） | `application.py:217-232` |
| 规避方式 | S8 体检/预演**不启动 FastAPI、不访问该端点**；真实实测也只走 CLI/评测脚本 | — |
| `AsyncTavilyClient.search` 签名 | `(self, query, search_depth: Literal['basic','advanced','fast','ultra-fast']=None, topic: Literal['general','news','finance']=None, ..., max_results=None, timeout=60.0, **kwargs) -> dict`，`iscoroutinefunction=True` | 本机 `tavily` 包 `inspect.signature` |
| 项目实际传参 | `query` / `max_results=3` / `search_depth='advanced'` / `topic ∈ {general, finance, news}` | `capabilities/tavily_retriever.py:166-171` |

**参数合法性核对结果：全部合法**（`advanced` 在 search_depth 字面量内；
`finance` / `news` / `general` 都在 topic 字面量内）。这一项此前被我口头说成
「风险点」，核对后确认**不是风险**，如实纠正。

**仍然未知、必须真实调用才能确认**（S8.2 的核心价值）：
`search()` 返回的 `dict` 结构、字段名是否为 `results`、每条是否含
`url` / `title` / `content` / `score`、score 的取值分布、content 长度、异常形态。
`capabilities/tavily_retriever.py:documents_from_results` 目前**假设**是
`response["results"]`，这点尚未被真实响应验证过。

## 5. S8.1 dry-run 预演结果（0 请求）

命令：`uv run python -m evals.live_dryrun` → `evals/live_dryrun.json`

| 项 | 实测 |
|---|---|
| 完整图轨迹 | `grounding → research → curate → evidence_check → rewrite_query →（2 次回退）→ degrade → briefing`，`research_runs=3` |
| 会发出的 query | **12 条**（3 轮 × 4 栏目），每条含确定性 sha256 cache key，回退轮换措辞 |
| `CallBudget` | `calls_made=0`、`dry_runs=12`、`cache_hits=0` |
| 外部连接 | `blocked_connection_attempts=0`，`socket_connect_restored=true` |
| 凭据探针 | Tavily key 解析 0 次、模型 key 解析 0 次、`AsyncTavilyClient` 构造 0 次（三处入口替换为计数器，非口头声明） |
| 报告 | `degraded=true`、拒答话术（dry-run 检索返回空，属预期，不是能力数据） |

query 清单采集自**生产检索路径** `CallBudget.queries`
（`TavilyRetriever._aget_relevant_documents`），不是脚本另写一套生成器冒充预演。

### 额度推算（推算值，非实测扣费）

依据 Tavily 官方计费页：免费 1000 credits/月，`basic` 1 credit/次、
`advanced` **2 credits/次**。项目默认 `advanced`：

> 12 次请求 × 2 credits = **最坏 24 credits / 公司**（无缓存时）。
> 3 家公司 ≈ 72 credits，约占免费月额度 7.2%。

`fast` / `ultra-fast` 的单价官方该页**未列出**，脚本不猜测，遇到时把
`worst_case_credits_per_company` 标为 `null` 并写明原因（已反向验证）。
缓存命中不扣额度，真实次数以 `CallBudget.calls_made` 为准。
**本次运行实际扣 0 credits。**

## 6. 历史阻塞项：S8.2 之前需要用户拍板（2026-11-14 21:20 已拍板）

| # | 决策 | 不替用户决定的原因 | 建议默认 |
|---|---|---|---|
| Q1 | 模型 key 用哪个 provider、是否允许产生费用 | 只从环境变量读，项目不存密钥；用户明确「谨慎使用、非必要不调用」 | 暂不给 → 只做检索层实测，不写模型准确率类数字 |
| Q2 | 是否放行 Tavily 额度、放行多少 | 免费额度有限，且 `advanced` 是 2 credits/次 | 先 `TAVILY_MAX_CALLS=1` 验证返回结构（2 credits），确认后再决定是否扩到 3–5 家 |
| Q3 | 真实 golden 谁标、标多少家 | 人工核验的标准答案不能由模型自己生成（循环论证） | 先 5 家 × 5 事实跑通口径，再决定是否扩到 30–50 家 |

**拍板结果（2026-11-14 21:20）**：

| 决策 | 用户选择 | 执行情况 |
|---|---|---|
| Q1 模型 provider | 阿里云百炼 DashScope，`qwen-plus` | `config/loader.py` 新增 `dashscope` provider + `LLM_BASE_URL` / `LLM_MODEL`；`LLM_PROVIDER` 锁定后不回退到其他 key。**尚未发起模型调用**（0 次） |
| Q2 Tavily 额度 | 放行 2–20 credits | S8.2 只花 **2 credits**（1 次 `advanced`），见第 8 节；剩余额度未动 |
| Q3 真实 golden | 助手查 5 家×5 条候选、用户复核 | `evals/golden_live_draft.jsonl` 已产出 25 条候选，全部 `pending_human_review`、0 条已核验，**复核前禁止作为指标来源** |

另外两条如实边界：

- `PostgresSaver` 仍未实现（`config/loader.py:278` 抛 `NotImplementedError`），S8 用 SQLite。
- 上游 `/models` 会出网，真实实测阶段不因「看一眼模型列表」白耗额度。

## 7. 本阶段不产出什么（防简历注水）

S8.0/S8.1 **没有**产出任何真实准确率、幻觉率、延迟、成本或真实检索语料。
`evals/scorecard.json` 里的 `1.000` 是 fixture 合成语料上的契约回归分，
**不能**写进简历当准确率。简历里的效果数字必须来自 S8.2 之后、
且能由 `docs/RESUME_EVIDENCE.md` 里的命令当场复现；复现不了就标「未测」。

---

## 8. S8.2 单次真实调用实测（2026-11-14 21:29，2 credits）

**做了什么**：`uv run python -m evals.live_probe` 经**生产检索路径**
（`make_document_tool` → `TavilyRetriever._aget_relevant_documents`）发出 1 次
`advanced` 检索，query = `Notion company overview background products`，
`max_results=3` / `topic=general`。产物 `evals/live_probe.json`。

**额度硬约束（非口头声明）**：`CallBudget(1)` + `RecordingClient` 在第 2 次
`search()` 调用处直接抛错；实测 `calls_made=1`、`sdk_search_invocations=1`、
`dry_runs=0`。同一 query 立刻再跑一次命中磁盘缓存 → `cache_hits=1`，
**后续复现不再扣额度**（缓存在 gitignored `evals/cache/tavily/`）。

**此前最大的未知已坐实**：`search()` 返回的顶层字段为
`query / follow_up_questions / answer / images / results / response_time / request_id`；
`results` 是 list，本次 3 条，每条含 `url / title / content / score`（另有
`id`、`raw_content=None`）。`capabilities/tavily_retriever.py:documents_from_results`
对 `response["results"]` 的**假设成立**：`contract_ok=true`，转出 3 个 Document，
`metadata_keys = [score, section, source, title, url]`，全部有 URL；
score 分布 `0.7174–0.8146`，content 长度 `794–2011` 字符。
分数都高于 `evidence.min_relevance_score=0.4`，说明该阈值在本次样本下不会误杀，
但**1 个样本不能推断分布**。

**密钥处理**：只在运行那一次用 `winreg` 读 Windows 用户级变量并在**进程内存**中
映射为 `TAVILY_API_KEY`；脚本自身拒绝去注册表取 key（无 key 直接抛错，有测试）。
产物不含正文、完整 URL、`tvly-` / `sk-` 任何密钥串；已用正则核对。

**计费**：官方 `advanced = 2 credits/次` × 1 次 = **2 credits（推算，不是账单）**。
官方未列单价的 `fast` / `ultra-fast` 依旧标 `null`，不猜数字。

**如实边界**：

1. 仅 **1 次请求 / 1 家公司 / 1 个栏目**，不产出 p95、平均成本、成功率或稳定性结论。
2. **0 次真实模型调用**：`qwen-plus` 的 `with_structured_output` 兼容性只做了
   0 调用构造验证（`tests/test_s8_dashscope.py`），尚未真调。
3. **没有产出真实准确率 / 幻觉率**：真实 golden 仍是待复核草稿，
   且 S7 的逐字匹配口径对真实报告不适用，S8.4 需先解决语义 judge 口径。
4. S7 `scorecard.json` 的 `1.000` 仍是合成语料契约回归分，**不得写进简历**。
5. 用户放行上限 20 credits，本阶段只用了 2，剩余未动。
