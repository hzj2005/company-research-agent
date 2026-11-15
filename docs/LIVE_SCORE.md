# S8.4 语义批改结果（AI judge，非人工评分）

> 一句话：**第一次把「你签字确认的中文标准答案」和「系统真跑出来的英文报告」对上了。
> 5 条里 0 条被完整支持、2 条判错、3 条没写到；这份结果主要暴露的是真机报告的质量问题，
> 不是「模型准确率」，也不能当准确率写进简历。**

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

| claim_id | 标准答案（节选） | 判定 | 报告里的逐字证据 |
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
3 条引文全部在 `evals/live_run.json` 的原始报告正文里逐字命中。另外核对：
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
支撑事实）未核验。**真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价仍是「未测」。**

## 6. 产物与下一步

- `evals/judge.py` — 三重放行、1 请求、0 检索、证据句逐字校验、失败如实落盘
- `evals/live_score.json` — 真实判定明细（唯一真结果）
- `evals/live_score_dryrun.json` — 0 调用链路自检占位，`must_not_be_used_as_metric=true`
- `tests/test_s8_judge.py` — 19 条护栏（含真实产物完整性检查）

下一步 **S8.5**：0 调用、不新增额度，把 fixture 契约回归分与这份真机判定并排放进
`docs/LIVE_REPORT.md` 对比表，明确「假数据满分 ≠ 真机效果好」；
再进 S8.6 简历数字出处表与 S9 简历描述。
