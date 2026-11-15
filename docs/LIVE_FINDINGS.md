# S8.3 真实实测结果（1 家公司 / 1 次运行）

> 生成：2026-11-14。用户放行 Tavily **20–50 credits**、阿里云百炼 `qwen-plus`、
> 5 家×5 条待人工复核的 golden 草稿。
> 原始产物：`evals/live_run.json`、`evals/llm_probe.json`、`evals/live_quality.json`、
> `evals/live_probe.json`（S8.2）。**本文件所有数字都能由这些文件当场复核。**
>
> **状态更新（S8.5，2026-11-15）**：本文是 S8.3 当时的实测快照，§4–§6 写的是**当时**的未完成项，
> 保留不改以维持时间线真实。之后 S8.4 已完成 25 条人工核验 golden（含 11 条用户修订）与
> 1 次真实 `qwen-plus` 语义 judge，S8.5 完成 fixture vs 真机对比表。当前口径以
> `docs/GOLDEN_LIVE.md`、`docs/LIVE_SCORE.md`、`docs/LIVE_REPORT.md` 为准；
> **真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价仍为「未测」**。

## 1. 实际花了多少

| 项 | 数值 | 依据 |
|---|---|---|
| Tavily 真实请求 | **3 次** + 1 次磁盘缓存命中 = 4 栏目各 1 query | `live_run.json: budget` |
| 本轮 credits | **6**（`advanced` = 2/次，缓存不扣） | `live_run.json: credits` |
| 累计 credits | **8 / 50**（含 S8.2 的 2） | 同上 |
| 模型请求 | **4 次** / `qwen-plus` | `live_run.json: llm_usage` |
| 模型 token | **7896**（prompt 5987 + completion 1909） | 同上 |
| 端到端耗时 | **62.9 s**（本机墙钟，含网络往返） | `live_run.json: timing` |

**没超预算，也没跑满**：4 个栏目首轮检索都达到 `sufficient`，没有触发自纠正回退，
所以只用了 12 次硬预算里的 3 次真实请求。`TAVILY_MAX_CALLS=12` 与 `CallBudget(12)` 双保险未触顶。

## 2. 跑通了什么

- `qwen-plus` 通过 DashScope OpenAI 兼容端点，`with_structured_output(method="function_calling")`
  **可用**：单独探针返回合规 `SectionBrief`，3 条 fact 的 URL 全部能回溯到给定文档
  （`evals/llm_probe.json`，1 次请求 / 748 tokens / 3.8 s）。
- 完整图真实运行成功：`grounding → research → curate → evidence_check → briefing`，
  无 retry、无降级、四栏目齐全；报告 **4998 字符 / 27 条结论 / 11 条 References**。
- 检索用的是**真实网页**：报告中的 11 个 URL 来自 10 个域名，
  不再有 `example.org` 合成链接；响应缓存在已 `.gitignore` 的 `evals/cache/tavily/`。
- 密钥只在运行时从 Windows 用户级变量映射进进程内存，未打印、未落盘、未提交；
  三个产物文件均通过 `sk-` / `tvly-` 正则扫描。

## 3. 失败案例（最重要，不能藏）

`evals/live_quality.py`（0 调用，词法检查）自动抓到 **1 处硬矛盾**：

> `Company Overview` 里同时写着
> `- Notion was founded in 2013. [6]`
> `- Notion was founded in 2014. [4]`

人工阅读同一栏目还看到：

- `Notion's headquarters is located at 51 Lloyd Baker Street, London, England` ——
  与官方口径（旧金山）不符，疑似检索到同名/低质量来源；
- `Notion was formerly known as Canopy Technologies`、`approximately 1,200 employees` 等
  未核验表述；
- 11 个来源里含 `medium.com` 等非一手渠道，`forbes.com` 出现 2 次。

**结论要说准**：`citation_integrity_ok = true` 只证明 27 个 `[n]` 都有对应编号，
**不证明**该 URL 真的支持结论，更不证明事实正确。真实语料把噪声带进来了，
而 S7 fixture 上的 `1.000` 完全掩盖了这一点——这正是「fixture 满分 ≠ 真实准确率」的实证。

## 4. 如实边界

1. **1 家公司、1 次运行**：不是统计意义的准确率、幻觉率或 p95；不能写成「准确率 X%」。
2. **没有真实准确率数字**：25 条 golden 仍是 `human_verified_claims = 0` 的草稿，
   且真实报告措辞不会与 `candidate_fact` 逐字一致，S7 的精确文本匹配会全判 0 分。
   S8.4 必须先解决语义 judge / 人工判定口径。
3. **没有真实成本数字**：`total_cost_usd = null`。`get_openai_callback` 的价目表只覆盖
   OpenAI 官方模型，qwen-plus 单价不在表内，**不套用、不编造**。
4. 矛盾检测只覆盖 `founded in YYYY` 这类显式模式，未覆盖同义改写的事实冲突；
   它是词法检查，不是语义 judge。
5. 本轮**未新增**任何「效果提升」结论；上述矛盾是待修复项，不是成果。

## 5. 可复现命令

```bash
# 0 额度：只读检查已有产物
uv run python -m evals.live_quality        # -> evals/live_quality.json
uv run python -m evals.build_golden --check
uv run pytest -q

# 需用户放行额度与 key（本轮已执行，不要重复烧额度）
# 从 Windows 用户级变量映射 TAVILY_API_KEY / SYSTEM_ALIYUN_APIKEY 到进程内存后：
uv run python -m evals.llm_probe           # 1 次模型调用，0 Tavily
uv run python -m evals.live_run            # 硬预算 12 次 / 上限 50 credits
```

## 6. 下一步

- **等你复核** `evals/golden_live_review.jsonl` 的 25 条 `user_verdict`（见 `docs/GOLDEN_REVIEW.md`）。
- 复核完才生成正式 golden，并解决语义匹配口径（S8.4）。
- 剩余额度：50 − 8 = **42 credits**，够再跑约 1–2 家；是否跑、跑哪家由你定。
- 简历数字只能引用本文件里能当场复现的数字；上述矛盾应作为「发现并定位的真实问题」写，
  不能包装成效果。
