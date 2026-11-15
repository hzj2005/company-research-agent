# 正式 golden（事实层人工核验，最终版）与标注口径

> 生成：2026-11-15（用户二次复核后重建）。产物：`evals/golden_live.jsonl`，由
> `evals/build_golden_live.py` 从用户导出的 `evals/golden_live_review_filled.jsonl` 只读生成。
> **0 次 API 调用、0 Tavily credits。**
> 用户结论：**「25 条答案我重新看了一下，有的部分我改了为最后标准答案」** —— 以用户最终版为准。

## 1. 这份文件是什么

| 项 | 值 |
|---|---|
| 规模 | 5 家公司 × 5 条 = **25 条事实** |
| 判定人 | 用户（不是 AI） |
| `provenance` | `human-verified` |
| 用户最终决定 | **14 条采纳原样 / 11 条改成最终标准答案 / 0 驳回** |
| 逐条备注 | 25 条全部带核对说明（页面预填的 AI 核对说明，由用户采纳；结论按钮仍由用户逐条点） |
| 生成方式 | 只读合并三份草稿/复核文件，不改写任何输入 |

每条 claim 同时保留**最终版**与**原始版**两套字段，防止旧草稿悄悄盖掉用户的修改：

- `expected_text` / `source_url`：用户最终事实与最终出处
- `original_fact` / `original_source_url`：草稿原文与原始出处（仅供对照审计）
- `ai_check` / `ai_note` / `evidence_quote_from_ai_check`：AI 逐条核对结论，一条没删
- `human_verdict` / `human_decision` / `human_note`：用户逐条点选的结果与备注

**11 条改了什么**（详见 `evals/golden_live_review_filled.jsonl`）：换掉 6 条打不开的
Business Wire / `wikipedia.com` 链接、把 Figma IPO 月份改成官方口径、把 Airbnb「已上市」
改成「公告预计开始交易」、`notion:company:2` 收敛创始人措辞，等等。
`claims_flagged_but_left_as_is = 0`：AI 标过问题的 10 条现在没有一条还留着原样。

## 2. 三层边界（最重要，不能混）

| 层 | 状态 | 能不能算指标 |
|---|---|---|
| **事实层**（这 25 句话对不对） | ✅ 用户二次复核、11 条改成最终版，全部确认 | 可以，但只限「报告有没有覆盖这些事实」 |
| **引用层**（这些 URL 能不能支撑这些话） | ⚠️ 6 条打不开的**原始** URL 已换成新 URL；但本项目**没有重新抓取新页面（0 调用）**，新链接能否打开、页面是否真的印着最终事实，均未实测 | **仍禁止**用于 `citation_traceability` / URL 可访问性 / `hallucination_rate` |
| **覆盖层**（有多少条真能对着报告比） | ⚠️ 目前**只有 Notion 1 家**有真实报告（`evals/live_run.json`） | 只能算 Notion 的 5 条；其余 4 家 20 条**无报告可比**，不得据此算全量准确率 |

**诚实规则**：换了 URL 的条目，`source_content` 一律为 `null`，
`source_content_for_final_url_verified = false`。AI 核对时读到的原文单独放在
`evidence_quote_from_ai_check`，并注明「不保证对应最终 URL」——**绝不把旧页面的引文
冒充成新页面的内容**。最终 URL 来源也标清楚了：16 条沿用原始、7 条用 AI 核对过的替代来源、
2 条是用户自己指定的（`notion:financial:0` 的 SiliconANGLE、`airbnb:industry:0` 的 Airbnb Newsroom）。

`notion:financial:0` 现在用用户自己找到的 SiliconANGLE 报道替换了原来的 CNBC 链接，
事实层按用户结论采纳；引用层只记「用户指定」，不冒充已在本项目核验过。

**对更早一轮措辞的精确化**：我曾说「这份 golden 不能算准确率」说过头了。准确说法是：
引用层不能算、全量准确率不能算；**Notion 那 5 条的事实层比对可以做**，但要先解决第 4 节的语义口径。

## 3. 为什么不能只换 `EVAL_DATASET_PATH` 复用 S7 脚本

`docs/ACTION_PLAN.md` 12.2 原计划写「换 `EVAL_DATASET_PATH` 即可复用 S7 脚本」。
S8.4 实际用只读探针（`uv run python` + `load_golden` / `load_eval_config`）验证，**该设想不成立**：

| # | 实测结果 | 代码依据 |
|---|---|---|
| 1 | 新 golden 的 `abstains = 0`（真实 golden 没有人工核验过的拒答样本，不能编） | `evals/run_eval.py` L205-206： `if not golden.claims or not golden.abstains: raise ValueError` |
| 2 | `config/eval.yaml` 的 `provenance` 写死 `synthetic-fixture-derived`，与 `human-verified` 冲突 | `config/eval.yaml` dataset 段；`evals/config.py` `DatasetConfig.provenance` |
| 3 | `fixture.cases = [sufficient, sparse, empty]`，与 live 的 5 个公司 case 不匹配 | `evals/run_eval.py` L210-212： `missing = [k for k in cfg.fixture.cases if k not in case_by_key]` |

所以 **S7 继续只做 fixture 契约回归（`evals/golden.jsonl`）**，live 必须走独立评分脚本。
这不是偷懒：S7 的 `1.000` 是「给定合成语料，系统该产出什么」的回归分，
live 是「真实网页 + 真实模型写出来的报告，覆盖了多少人工确认的事实」，两者本来就不是同一个指标。

## 4. S8.4 语义判定（已完成，2026-11-15）

真实报告是**英文**，正式 golden 的事实是**中文**：
`Notion 于 2013 年创办` vs `Notion was founded in 2013.` 逐字匹配必然判 0 分，
`evals/metrics.py` 的精确文本匹配口径在真实语料上失效。

**用户选择方案 A**：`evals/judge.py` 用 1 次 `qwen-plus` 结构化输出批量判定
`supported / refuted / not_mentioned` + 报告里的逐字证据句。真实调用需
`--live` + `JUDGE_LIVE=1` + `DASHSCOPE_API_KEY` 三重放行；`max_retries=0`，
Tavily 装哨兵，失败如实落盘不重试。prompt **不送**任何出处/AI 备注字段，
证据句必须能在报告里逐字核到，核不到标 `quote_check_failed`。

结果：**1 次请求 / 2776 tokens / 0 Tavily credits**，5 条全判定，
`supported=0 / refuted=2 / not_mentioned=3 / self_conflict=1`，
确实复现了 `docs/LIVE_FINDINGS.md` 里 `founded in 2013` 与 `2014` 的矛盾，
并新抓出 Financial 栏目整段实体混淆（Notion VTec Berhad）。
完整明细、独立复核、一处 judge 措辞瑕疵与指标边界见 **`docs/LIVE_SCORE.md`**。

产物标 `is_human_adjudicated=false`、`usable_as_resume_metric=false`：
AI judge 未经人工抽检一致率校准，样本仅 1 家 5 条，引用层未核验。

## 5. 简历可用性（如实）

现在能写的：**「25 条真实事实经人工二次复核（11 条修订），落成正式 golden」**、
**「建立语义 judge 链路，1 次真实模型请求，在真机报告上定位出自相矛盾 / 来源污染 /
实体混淆 3 类问题」**、架构/工程能力、Notion 真机报告的
6 credits / 4 次模型请求 / 62.9 s / 4998 字符（可当场复现）。
**仍不能写**：准确率 X%、幻觉率 X%、p95、成本单价、`citation_traceability` 数值 ——
这些要么还没测，要么因引用层未实测而不能算。S7 的 `1.000` 是 fixture 分，
S8.4 的 `supported=0` 是 5 条 AI 判定明细，两者都不得当效果数字用。

## 6. 复现命令

```bash
uv run python -m evals.build_golden_live    # 0 调用，重生成 evals/golden_live.jsonl
uv run python -m evals.build_golden --check
uv run python -m evals.judge                # 默认 dry-run，0 调用、0 额度
uv run pytest -q
```

真实判定会消耗 1 次模型请求，需显式三重放行（不要误跑）：

```bash
JUDGE_LIVE=1 DASHSCOPE_API_KEY="$SYSTEM_ALIYUN_APIKEY" uv run python -m evals.judge --live
```
