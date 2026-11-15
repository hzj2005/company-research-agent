# S8.5 假数据契约回归 vs 真机表现（对比表）

> **一句话**：fixture 上的满分是「流程契约没崩」，真机第一份报告就暴露了自相矛盾、来源污染、实体混淆三类硬伤。两侧测的不是同一个东西，**不能相减、不能说「掉了多少」，更不能用 fixture 的数字冒充真实效果**。
>
> 本文由 `evals/build_live_report.py` 从 6 份既有产物生成，生成时禁网守卫拦截到 **0** 次外部连接，**0 次模型请求 / 0 Tavily credits**。每个数字后标「文件 → 字段」，可用 `tests/test_s8_live_report.py` 逐项重算。**请勿手改本文**，要改请改生成脚本。

## 0. 怎么复现

```bash
uv run python -m evals.build_live_report       # 只读 6 份产物，重新生成本文
uv run pytest -q tests/test_s8_live_report.py  # 逐个数字按出处重算
```

生成脚本复用 `evals/run_eval.py` 的禁网守卫：非回环连接立即抛错，因此这条命令**物理上不可能**消耗 Tavily / 模型额度；本次实测拦截计数 0。

## 1. 先讲清口径：两侧根本不是一回事

| 维度 | fixture 契约回归（S7） | 真机实测（S8） |
|---|---|---|
| 语料 | 合成 fixture 〔`evals/scorecard.json` → `provenance`〕 | 真实网页检索结果 〔`evals/live_run.json` → `config.app_mode`〕 |
| 样本规模 | 3 〔`evals/scorecard.json` → `runs.baseline.counts.cases`〕 | 仅 `Notion` 一份真实报告 〔`evals/live_run.json` → `company`〕 |
| 待比对事实条数 | 23 〔`evals/scorecard.json` → `runs.baseline.counts.expected_claims`〕 | 5 〔`evals/live_score.json` → `dataset.scored_claims`〕 |
| 判定方式 | 精确文本匹配 + 词法包含代理 〔`evals/scorecard.json` → `disclaimer`〕 | AI 语义 judge（qwen-plus） 〔`evals/live_score.json` → `method`〕 |
| 外部 LLM 调用 | 0 〔`evals/scorecard.json` → `external_calls.llm`〕 | 4 〔`evals/live_run.json` → `llm_usage.successful_requests`〕 |
| 外部 Tavily 调用 | 0 〔`evals/scorecard.json` → `external_calls.tavily`〕 | 3 〔`evals/live_run.json` → `budget.calls_made`〕 |
| 产物性质 | CI 回归门禁（流程契约不崩） 〔`evals/scorecard.json` → `summary.baseline_gate_passed`〕 | 单次运行观察（不做统计推断） 〔`evals/live_score.json` → `usable_as_resume_metric`〕 |

fixture 侧 `provenance = synthetic-fixture-derived`、`mode = fixture`，文件自带免责声明原话：

> fixture 合成语料上的可机器核验契约指标，不是真实世界准确率/成本。citation_traceability 为词法包含代理判定，不等价语义蕴含；真实指标需 APP_MODE=live + 人工核验 golden（S8）。

真机侧只有一份报告、一次运行，**没有统计意义上的分布**；`p95` / 成本 / 准确率这类需要多样本与人工判定的指标，一律按「未测」处理。

## 2. 核心对比表（逐项说清「真机到底测没测」）

| 指标 | fixture 侧 | 真机侧 | 说明 |
|---|---|---|---|
| 事实准确率 `fact_accuracy` | 1.0 〔`evals/scorecard.json` → `runs.baseline.metrics.fact_accuracy`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | 真机侧只有 5 条 AI 判定明细（supported=0 / refuted=2 / not_mentioned=3），另有 20 条没有卷子可比；判定明细不是准确率。 |
| 引用可追溯 `citation_traceability` | 1.0 〔`evals/scorecard.json` → `runs.baseline.metrics.citation_traceability`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | fixture 侧是词法包含代理判定；golden 的最终 URL 是否支撑事实未核验，引用层不能出分。 |
| 幻觉率 `hallucination_rate` | 0.0 〔`evals/scorecard.json` → `runs.baseline.metrics.hallucination_rate`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | 真机报告确有事实错与实体混淆，但没有人工判定的幻觉样本统计，不能换算成比率。 |
| p95 延迟 `p95_latency_ms` | 2379.819 〔`evals/scorecard.json` → `runs.baseline.metrics.p95_latency_ms`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | fixture 数值是合成语料上的本机墙钟；真机只有单次 62875.8 ms 墙钟，不是 p95。 |
| 单份成本 `cost_per_report` | 0.0 〔`evals/scorecard.json` → `runs.baseline.metrics.cost_per_report`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | fixture 侧 0 外部调用故为 0；真机 `llm_usage.total_cost_usd` 为 null，qwen-plus 单价不套用、不编造。 |
| 拒答率 `abstain_rate` | 1.0 〔`evals/scorecard.json` → `runs.baseline.metrics.abstain_rate`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | fixture 有专门的拒答样本；真机单次报告 `report_checks.abstain_markers` 为 0，不构成拒答率统计。 |
| 自纠正成功 `self_correction_success` | 1.0 〔`evals/scorecard.json` → `runs.baseline.metrics.self_correction_success`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | 真机首轮四个栏目都判 sufficient，`graph.retry_count` 为空，自纠正路径未触发。 |
| 平均重试轮次 `avg_retry_rounds` | 1.0 〔`evals/scorecard.json` → `runs.baseline.metrics.avg_retry_rounds`〕 | 未测 〔`evals/live_score.json` → `metric_boundary.must_not_be_called`〕 | 同上：真机未触发重试，没有可统计的轮次样本。 |
| LLM 请求数（同一阶段累计口径不同，仅作事实对照） | 0 〔`evals/scorecard.json` → `external_calls.llm`〕 | 4 〔`evals/live_run.json` → `llm_usage.successful_requests`〕 | fixture 是产物声明的 0 调用；真机是端到端一份报告的完成请求数，不含 S8.4 judge 的那 1 次。 |
| Tavily 请求数 | 0 〔`evals/scorecard.json` → `external_calls.tavily`〕 | 3 〔`evals/live_run.json` → `budget.calls_made`〕 | fixture 0 调用；真机另有 1 次磁盘缓存命中，缓存不扣额度。 |

**表里最容易被误用的一格**：`p95_latency_ms = 2379.819` 与 `cost_per_report = 0.0` 都在 fixture 合成语料 + 0 次 LLM / 0 次 Tavily 调用下产生。真机那份报告的单次墙钟是 62875.8 ms（`timing.note` 明写「不代表 p95」），`llm_usage.total_cost_usd` 是 `null`。**这几个数不是真实 p95、不是真实成本；准确说法是：fixture 侧有值、真机侧全部未测。**

## 3. 真机侧实测事实（可逐个复核）

| 项 | 值 | 出处 / 说明 |
|---|---|---|
| 报告 company | Notion 〔`evals/live_run.json` → `company`〕 | 本次唯一一份真实报告 |
| 报告字符数 | 4998 〔`evals/live_run.json` → `report_checks.chars`〕 | 报告正文长度，不是质量分 |
| 行内引用标记 | 27 〔`evals/live_run.json` → `report_checks.inline_citation_markers`〕 | 只数正文，References 的 `[n]` 不计入 |
| References 条数 | 11 〔`evals/live_run.json` → `report_checks.reference_lines`〕 | 编号齐全 ≠ URL 真的支撑结论 |
| 真实 Tavily 请求 | 3 〔`evals/live_run.json` → `budget.calls_made`〕 | 四个栏目各 1 query，其中 1 次命中磁盘缓存 |
| 缓存命中 | 1 〔`evals/live_run.json` → `budget.cache_hits`〕 | 缓存命中不扣 credits |
| 本轮 credits | 6 〔`evals/live_run.json` → `credits.spent_this_run`〕 | 按官方 advanced=2 credits/次推算，非账单 |
| 累计 credits | 8 〔`evals/live_run.json` → `credits.cumulative`〕 | 用户放行上限见下行，本阶段未再消耗 |
| 用户放行上限 | 50 〔`evals/live_run.json` → `credits.user_ceiling`〕 | 额度纪律：非必要不调用 |
| 模型请求 | 4 〔`evals/live_run.json` → `llm_usage.successful_requests`〕 | qwen-plus，生产链路 |
| 模型 tokens | 7896 〔`evals/live_run.json` → `llm_usage.total_tokens`〕 | get_openai_callback 捕获 |
| 单次墙钟 ms | 62875.8 〔`evals/live_run.json` → `timing.elapsed_ms`〕 | 含网络往返，非确定性字段，不是 p95 |
| 词法矛盾 | 1 〔`evals/live_quality.json` → `checks.contradiction_count`〕 | 同一栏目同时写 2013 / 2014 成立 |
| 来源域名数 | 10 〔`evals/live_quality.json` → `checks.source_domain_count`〕 | 含 medium.com 等非一手渠道 |
| 引用编号完整性 | true 〔`evals/live_quality.json` → `checks.citation_integrity_ok`〕 | 只证明 `[n]` 有对应编号，不证明事实正确 |
| judge 判定的事实 | 5 〔`evals/live_score.json` → `dataset.scored_claims`〕 | 其余标准答案没有真实报告可比，如实跳过 |
| 跳过的事实 | 20 〔`evals/live_score.json` → `dataset.skipped_claims`〕 | 不凭空生成卷子 |
| 判定 supported | 0 〔`evals/live_score.json` → `summary.supported`〕 | 报告有支持该事实的陈述；不等于来源 URL 真的支持它 |
| 判定 refuted | 2 〔`evals/live_score.json` → `summary.refuted`〕 | 含同一事实自相矛盾的情形 |
| 判定 not_mentioned | 3 〔`evals/live_score.json` → `summary.not_mentioned`〕 | 报告没写到，不等于答错 |
| 自相矛盾标记 | 1 〔`evals/live_score.json` → `summary.self_conflict`〕 | 同一事实给了冲突取值，按 prompt 规则判不可靠 |
| 证据句核对失败 | 0 〔`evals/live_score.json` → `summary.quote_check_failed`〕 | 引文必须能在报告正文逐字核到 |
| judge 模型请求 | 1 〔`evals/live_score.json` → `usage.successful_requests`〕 | 单独一次，max_retries=0，不与生产链路混算 |
| judge tokens | 2776 〔`evals/live_score.json` → `usage.total_tokens`〕 | 成本单价为 null，不编造 |
| 审计重算差异条数 | 0 〔`evals/live_score_audit.json` → `recheck.delta_vs_original`（列表长度）〕 | S8.4 复查修复后，既有判定结论无变化 |
| 审计新增外部调用 | 0 〔`evals/live_score_audit.json` → `isolated_calls.llm_requests`〕 | 事后审计 0 模型 / 0 credits |
| dry-run 最坏预算 | 24 〔`evals/live_dryrun.json` → `credit_estimate.worst_case_credits_per_company`〕 | 按官方规则推算的上界，不是实测扣费 |
| dry-run query 数 | 12 〔`evals/live_dryrun.json` → `budget.query_count`〕 | 完整图最坏情况的 query 清单长度 |

额度纪律：累计 **8 / 50 credits**（S8.2 探针 + S8.3 端到端），S8.4 的 judge 与 S8.5 的本文都是 0 credits。

## 4. 为什么 `fact_accuracy = 1.0` 只是「流程契约分」：A/B 组就是证据

| 组 | 关掉的开关 | `fact_accuracy` | `citation_traceability` | `hallucination_rate` |
|---|---|---|---|---|
| `baseline` | `（无）` | 1.0 〔`evals/scorecard.json` → `runs.baseline.metrics.fact_accuracy`〕 | 1.0 〔`evals/scorecard.json` → `runs.baseline.metrics.citation_traceability`〕 | 0.0 〔`evals/scorecard.json` → `runs.baseline.metrics.hallucination_rate`〕 |
| `no_inline_citations` | `{"features.inline_citations": false}` | 1.0 〔`evals/scorecard.json` → `runs.no_inline_citations.metrics.fact_accuracy`〕 | 0.0 〔`evals/scorecard.json` → `runs.no_inline_citations.metrics.citation_traceability`〕 | 1.0 〔`evals/scorecard.json` → `runs.no_inline_citations.metrics.hallucination_rate`〕 |
| `self_correction_off` | `{"features.self_correction": false}` | 0.869565 〔`evals/scorecard.json` → `runs.self_correction_off.metrics.fact_accuracy`〕 | 1.0 〔`evals/scorecard.json` → `runs.self_correction_off.metrics.citation_traceability`〕 | 0.0 〔`evals/scorecard.json` → `runs.self_correction_off.metrics.hallucination_rate`〕 |

关掉行内引用，`citation_traceability` 从 1.0 掉到 0.0、`hallucination_rate` 升到 1.0，而 `fact_accuracy` 纹丝不动；关掉自纠正，`fact_accuracy` 变成 0.869565。**分数随开关变化，说明它测的是「图有没有按预期执行」，不是「报告写得好不好」。**（`p95_latency_ms` 是非确定性字段，不参与 A/B 判定，故本表不列。）

## 5. 已知问题：真机报告的三类硬伤（项目发现，未修）

| 问题 | 证据 | 可能原因（待验证） |
|---|---|---|
| 自相矛盾 | 同一 Company 栏目同时写 2013 / 2014 年成立 〔`evals/live_quality.json` → `checks.contradictions[0].values`〕；`checks.contradiction_count` = 1 〔`evals/live_quality.json` → `checks.contradiction_count`〕 | 多来源未做冲突消解，结构化抽取把两句都当事实收下 |
| 来源污染 / 事实错 | 总部写成伦敦某门牌；来源域名共 10 个 〔`evals/live_quality.json` → `checks.source_domain_count`〕，含 `medium.com`（有记录） 〔`evals/live_quality.json` → `checks.source_domains`〕 | 同名实体 / 低质来源混入，检索 query 未消歧 |
| **实体混淆** | Financial 栏目正文里 `Notion VTec Berhad` 出现 **11** 次 〔`evals/live_run.json` → `report`（词频）〕，是马来西亚上市公司 0083.KL 的股价指标，与 Notion Labs 不是同一家 | 检索命中同名股票代码，未做实体一致性检查 |
| judge 措辞瑕疵 | `is_human_adjudicated = false` 〔`evals/live_score.json` → `is_human_adjudicated`〕；`notion:company:2` 的 reason 漏看了正文里出现过一次的 CEO 提及 | AI judge 未经人工抽检一致率校准，故产物标 `usable_as_resume_metric=false` |

这三类是**真实运行才暴露**的问题，fixture 满分完全测不出来。能把问题定位到具体栏目、具体来源域名、具体实体名，正是「评测链路可用」的证据——比一个漂亮的分数更经得住面试追问。S8.5 只做记录与对比，**不修、也不复测**（复测要另花 Tavily 额度，需单独规划）。

## 6. 不能写成什么（红线清单）

- ❌ `fact_accuracy = 1.0` 写成「系统效果好 / 准确率高」——它是合成语料契约回归分，§4 已证随开关变化。
- ❌ `supported = 0`（共 5 条）写成「准确率 0%」——其中 3 条是「报告没写到」，不是「写反了」；judge 是 AI 判定、非人工评分。
- ❌ 把 `p95_latency_ms = 2379.819` 或单次墙钟 62875.8 ms 写成「真实 p95」。
- ❌ 把 `cost_per_report = 0.0` 写成「零成本」——那来自 0 次外部调用；`total_cost_usd = null` 就保持 null，不套用 qwen-plus 之外的价目表。
- ❌ 把 25 条 golden 写成「都测了」——当前只有 5 条有真实报告可比，另 20 条如实跳过。
- ❌ 编造真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价；golden 引用层（最终 URL 是否支撑事实）未核验，引用类指标尤其不能出数。
- ❌ 写「上线 / 甲方 / 用户量 / 效果提升 X%」——本项目是个人工程复现，没有这些事实。

## 7. 能写进简历的（工程事实，不是效果数字）

- 基于 LangGraph 的公司调研 Agent：并行子图检索、栏目级自纠正、结构化输出、HITL 中断/恢复、checkpoint 持久化；fixture/live 双模式 + 禁网守卫 + 调用预算三重放行。
- 建立 25 条人工核验 golden 与 AI 语义 judge 链路，把真机报告的问题定位到栏目与来源级别（§5）。
- 累计 8 / 50 credits 的额度纪律下完成 1 份端到端真实报告；S8.4 复查用只读探针坐实并修复评测链路缺陷（见 `docs/LIVE_SCORE.md` §7），事后审计重算无差异。
- 评测台 + CI 回归门禁：A/B 组能量化各开关对契约指标的影响。

本段复用的数字（golden 条数、累计 / 上限 credits）与 §3 同源，由同一批字段插值生成，出处见 §3 对应行与 §8 产物索引；这里不引入任何新测量值。

## 8. 输入产物索引

| 文件 | 在本文里的角色 |
|---|---|
| `evals/scorecard.json` | fixture 契约回归分、A/B 组、0 外部调用声明 |
| `evals/live_run.json` | Notion 端到端真实报告、预算/额度/耗时 |
| `evals/live_quality.json` | 0 调用词法质量检查（矛盾、来源域名、引用编号） |
| `evals/live_score.json` | 5 条 AI 语义判定与指标边界 |
| `evals/live_score_audit.json` | S8.4 复查的 0 差异事后审计 |
| `evals/live_dryrun.json` | 0 调用预算推算（最坏 query 数 / credits 上界） |

## 9. 状态

- 本文生成：**0** 次外部连接、**0** 次模型请求、**0** Tavily credits；累计 Tavily 仍 **8 / 50**。
- 真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价：**未测**；上面的累计额度取自 `evals/live_run.json` → `credits.cumulative` / `user_ceiling`。
- 后续进度（状态注记）：S8.6 `docs/RESUME_EVIDENCE.md` 简历数字出处表**已完成**，本文引用的核心真机数字在那里都有逐条出处、commit 与复现命令；当前仅剩 S9 简历描述 + 面试追问清单。
