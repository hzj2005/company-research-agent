# S8.4 语义批改结果（AI judge，非人工评分）

> 一句话：**第一次把「你签字确认的中文标准答案」和「系统真跑出来的英文报告」对上了。
> 5 条里 0 条被完整支持、2 条判错、3 条没写到；这份结果主要暴露的是真机报告的质量问题，
> 不是「模型准确率」，也不能当准确率写进简历。**

> **S10 追注（2026-11-15，本文件其余内容不动）**：下面 §4 把 `notion:company:0` 的
> `refuted` 归因为「多来源未做冲突消解」。回看 `evals/cache/tavily/` 的原文后已修正：
> CB Insights 那一页写的是 `notion.online`（音乐时尚内容公司，2014 年伦敦成立），
> 和做协作工具的 Notion 只是重名 —— 所以「2013 与 2014 矛盾」「总部写成伦敦门牌」
> 是**同一个根因：同名不同实体**。修复见 `docs/ACTION_PLAN.md` 12.20；
> 本文的判定数字保留原样，因为它们描述的是**修复前**那份报告。

## 1. 这次真实发生了什么

| 项 | 值 | 证据 |
|---|---|---|
| 真实模型请求 | **1 次**（`qwen-plus`，`max_retries=0`，无重试） | `evals/live_score.json` → `usage.successful_requests` |
| token | 2776（prompt 2334 / completion 442） | 同上 `usage` |
| Tavily 调用 / credits | **0 / 0** | `isolation.tavily_client_search_calls`、哨兵 |
| 累计 Tavily | 仍 **8 / 50** | `evals/live_run.json` → `credits.cumulative`，本轮未动 |
| 成本单价 | `null`（不编造） | `get_openai_callback` 价目表不覆盖 qwen-plus |
| 耗时 | 本机墙钟，不参与 CI 比对 | `elapsed_ms` |

调用条件三重放行：`--live` + `JUDGE_LIVE=1` + `DASHSCOPE_API_KEY` 存在。
密钥只从用户级 `SYSTEM_ALIYUN_APIKEY` 映射进本进程内存，产物只记长度、不记值。

## 2. 五条判定明细

判定来自 `evals/live_score.json`；`evals/judge.py` 送进 prompt 的只有
`claim_id` + `expected_text` + 报告正文，**不送** `source_url` / `source_content` /
`ai_note` / `human_note`，避免 judge 拿标准答案的出处替报告脑补证据。

| claim_id | 标准答案（节选） | 判定 | 报告正文依据（前两行为逐字引文，其余为说明） |
|---|---|---|---|
| `notion:company:0` | 2013 年创办 | **refuted**（`self_conflict=true`） | 同时写了 `Notion was founded in 2013. [6]` 和 `Notion was founded in 2014. [4]` |
| `notion:company:1` | 总部旧金山 | **refuted** | `Notion's headquarters is located at 51 Lloyd Baker Street, London... [4]` |
| `notion:company:2` | CNBC 榜单列 3 位创始人 | not_mentioned | 正文未把任何人列为创始人 |
| `notion:industry:0` | 模块化工作区，组合笔记/项目/wiki/数据库 | not_mentioned | 只写了 "online work collaboration platform for task and project management" |
| `notion:financial:0` | 2021-10 完成 2.75 亿美元融资 | not_mentioned | Financial 栏目 11 条全是 `Notion VTec Berhad (0083.KL)` 的股票指标 |

汇总：`supported=0 / refuted=2 / not_mentioned=3 / unjudged=0 / self_conflict=1 /
quote_check_failed=0`。其余 20 条标准答案**如实跳过**（没有真实报告可比，不凭空造卷子）。

**三条口径，别误读：**

1. **`supported=0` ≠ 系统全错**。3 条是「报告没写到」，不是「写反了」；
   `not_mentioned` 不等于答错，只说明覆盖不足。
2. **2013 那条为什么算 refuted**：报告里确实有一句 2013 是对的，但同一栏目还有一句
   2014。按本次 prompt 的明确规则「报告对同一事实给冲突取值 → refuted + self_conflict」，
   判它不可靠。这是**口径选择**，不是 judge 没看懂 2013。
3. **References 不算事实陈述**：`[8]` Forbes 标题里带 "Reaches $10 Billion Valuation"，
   但报告正文没有陈述这条事实，所以 `notion:financial:0` 判 `not_mentioned`。
   prompt 已写明「References 只是来源清单」。

## 3. 独立复核（不靠脚本自证）

脚本自己打了 `quotes_verified=true`，我又用**不做任何归一化的精确子串**重新核一次：
3 条引文全部在 `evals/live_run.json` 的原始报告正文里逐字命中。
（脚本内的自动校验口径是「归一化空白 / `[n]` / 大小写后比对正文」，不是原始逐字；
本次 3 条引文连更严的原始逐字校验也通过，见 §7 复查。）另外核对：
`founded in 2013` × 1、`founded in 2014` × 1、`San Francisco` × 0、`London` × 1、
`Simon Last` / `Akshay Kothari` / `modular` / `wiki` / `database` / `Series C` 均 × 0、
`Notion VTec Berhad` × 11。三态计数之和 = 5 = 条目数，schema 无缺漏/重复/未知 id。
这组检查已固化成 `tests/test_s8_judge.py` 的真实产物护栏（文件不存在则诚实 skip）。

**发现一处 judge 措辞瑕疵，如实记录**：`notion:company:2` 的 reason 写
"does not mention ... Ivan Zhao as CEO"，但报告 Industry 栏目其实出现过
`per CEO Ivan Zhao's 'Legos' analogy`（1 次）。最终判定 `not_mentioned` 仍成立
（报告没说他是创始人、没提另两人、没提 CNBC 榜单），但 reason 的措辞不够精确。
这正说明 **AI judge 需要人工抽检一致率校准**，是 `usable_as_resume_metric=false` 的实证理由，
不是把结果删掉重跑的理由。

## 4. 这份结果真正的价值：真机报告被抓出三类硬伤

| 硬伤 | 具体表现 | 可能原因（待验证，未修） |
|---|---|---|
| 自相矛盾 | 同一 Company 栏目同时写 2013 和 2014 成立 | 多来源未做冲突消解，结构化抽取把两句都当事实收下 |
| 事实错 / 来源污染 | 总部写成伦敦某具体门牌；混入 `medium.com` | 同名实体/低质来源混入，检索 query 未消歧 |
| **实体混淆** | Financial 栏目 11 条全是马来西亚上市公司 Notion VTec Berhad 的股价指标 | 检索命中同名股票代码 `0083.KL`，未做实体一致性检查 |

这些是**真实运行才暴露的问题**，fixture 满分测不出来。它们不阻塞 S8.5/S9，
但应作为「已知问题」写进项目说明——能把真机问题定位到具体栏目和具体来源，
本身就是评测链路可用的证据。

## 5. 指标边界（写简历前必读）

| 可以说 | 不可以说 |
|---|---|
| 「建立了 25 条人工核验 golden + 语义 judge 链路，真机报告上定位到自相矛盾、实体混淆等 3 类问题」 | 「系统准确率 0%」/「准确率 60%」/「幻觉率 X%」 |
| 「1 次真实 judge 请求、2776 tokens、0 Tavily credits」 | 「单次成本 ¥X」/「p95 = X 秒」 |
| 「fixture 契约回归 1.000，真机 5 条判定明细」 | 「fixture 满分说明效果好」 |

原因写进产物 `metric_boundary`：① 样本仅 1 家 5 条；② judge 是 AI 判定、
未经人工抽检一致率校准（§3 已实锤一处措辞瑕疵）；③ golden 引用层（最终 URL 是否
支撑事实）未核验。

**特别提醒（S8.5 复查探针发现）**：`evals/scorecard.json` 的
`runs.baseline.metrics` 里**确实有** `fact_accuracy=1.0`、`citation_traceability=1.0`、
`hallucination_rate=0.0`、`p95_latency_ms=2379.819`、`cost_per_report=0.0`。
这些全是 **fixture 合成语料 + 0 外部调用**下的契约回归数（文件自带 `disclaimer`
已声明「不是真实世界准确率/成本」），**不是真实 p95、不是真实成本**。
准确说法是：这几项**fixture 侧有值、真机侧全部未测**；
真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价一律「未测」。

## 6. 产物与下一步

- `evals/judge.py` — 三重放行、1 请求、0 检索、证据句正文校验、失败留痕、运行时指纹
- `evals/live_score.json` — 真实判定明细（唯一真结果，**复查中一字未改**）
- `evals/live_score_dryrun.json` — 0 调用链路自检占位，`must_not_be_used_as_metric=true`
- `evals/audit_score.py` / `evals/live_score_audit.json` — 0 调用事后审计（§7）
- `tests/test_s8_judge.py`（25 条）+ `tests/test_s8_score_audit.py`（5 条）— 共 30 条护栏

## 7. 复查与修复（2026-11-15 12:22，0 调用 / 0 credits）

用户按惯例要求「先检查上一步」。只读探针坐实 **6 个真问题**，不是走形式：

| # | 问题 | 坐实方式 | 修复 |
|---|---|---|---|
| 1 | **References 标题能冒充正文证据句** | 探针：Forbes 标题在 References 里、不在正文，旧 `quote_in_report` 却返回 `True` | 新增 `report_body()`，证据句只在 `## References` 之前核 |
| 2 | **`not_mentioned` 塞编造引文不标失败** | 探针：塞 `"THIS IS INVENTED BY JUDGE"`，`quote_check_failed` 仍是 `False` | 任何 verdict 有核不到的引文一律标失败 |
| 3 | **schema 缺条目时 status 仍写 `ok`** | 探针：只返回 1/5 条，`status=ok` 但 `unjudged=4` | 改为 `partial`，与 `main()` 返回码一致 |
| 4 | **前置检查失败不落盘**，与「失败如实落盘」不符 | `common_inputs()` 等原本在 `try` 外 | `main()` 兜底写独立 `live_score_failed.json`，**不覆盖成功产物** |
| 5 | **产物无输入/代码指纹**（S7 早有 `code_sha256` 先例） | `has_any_hash_field=False` | `judge.py` 加运行时 `fingerprints()`；既有产物由 §7 审计事后补记 |
| 6 | 跨盘符路径让 `relative_to(ROOT)` 抛错 | 新增护栏测试实测失败 | 打印改用文件名 |

另外修正两处措辞：自动校验是「归一化后比对」而非「原始逐字」；§2 表格列名
对 `not_mentioned` 行原本不成立。

**修复是否改变既有结论**：`evals/audit_score.py` 用新口径重算 5 条，
`delta_vs_original = []`、`verdicts_changed = []` —— **0 差异，5 条判定一条没变
，3 条引文仍全部落在报告正文**。原始 `live_score.json` 一个字未改，
审计产物里用 `source_artifact_sha256` 锚定到这份具体文件。

**指纹是事后补记，不冒充运行时采集**：`recorded_after_run=true`；
`judge_py_at_run_commit_sha256` 取自 git `3e16906`（真实判定完成后的首个提交，
运行结束到提交之间 `judge.py` 未编辑）。下次真实运行会由 `judge.py` 在运行时
自动写 `provenance`，两者口径不同，文档如实区分。

**状态**：全量 **236 passed**、`uv pip check` 103 包兼容、Tavily 仍 **8/50**、
本轮 0 次模型请求 / 0 credits。

下一步 **S8.5**：0 调用、不新增额度，把 fixture 契约回归分与这份真机判定并排放进
`docs/LIVE_REPORT.md` 对比表，明确「假数据满分 ≠ 真机效果好」，并把 §4 的三类硬伤
列为已知问题；再进 S8.6 简历数字出处表与 S9 简历描述。

> **状态注记（S8.6，2026-11-15）**：上面这段是 S8.4 当时的快照，原文保留不改。
> S8.5 对比表、S8.6 `docs/RESUME_EVIDENCE.md` 数字出处表均已完成；
> 本文涉及的数字在出处表里都有逐条 commit 与可执行复现命令。
> 当前仅剩 S9 简历描述 + 面试追问清单；真实效果指标仍为「未测」。
