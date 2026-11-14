# 真实 golden 候选：AI 辅助复核清单

> 生成：2026-11-14。对应 `evals/golden_live_draft.jsonl`（25 条候选）与 `evals/golden_live_review.jsonl`（逐条证据）。
>
> **这是 AI 辅助核对，不是人工复核**：`human_verified_claims = 0`，25 条 `user_verdict` 全为 `null`。
> 逐条打开原始 URL 读了页面原文，不采信搜索摘要；但**最终采纳与否必须由你确认**——
> 同一个 AI 既出题又批卷，标准答案就失去意义，面试一问就穿。
> 本轮 **0 Tavily credits、0 次模型调用**。

## 怎么点（约 5 分钟）

打开 `evals/golden_live_review.jsonl`，看每条的 `evidence_quote`（页面上真实印着的原文）和 `note`，
把 `user_verdict` 从 `null` 改成 `true`（采纳）或 `false`（驳回）。
`needs_fix` / `reject` 的条目请一并确认 `suggested_source_url` 与 `suggested_fact`。
全部填完告诉我，我再生成正式 `evals/golden_live.jsonl`。

## A. 建议直接通过（15 条）

出处可访问、原文确实支持候选事实：

- **Notion** `company:0/1/2`、`industry:0` — CNBC 页面顶部字段与正文第 2 段逐字一致
- **Figma** `company:0/1`、`industry:0` — 官方 blog 的 About Figma 段与董事会名单
- **Stripe** `industry:0`、`company:0/1/2`、`financial:0` — 官方 newsroom 全部命中，质量最高的一组
- **Airbnb** `company:0/1/2` — 官方法文版 About us 与时间线

几处小提醒（不影响采纳）：Stripe 两条创始人、Airbnb 创始人名单在页面上是**分行排版**，
草稿的 `source_excerpt` 拼成了一行，不是逐字引文；Figma `industry:0` 的引文是截断片段，页面用弯引号且句子更长。
`stripe:financial:0` 的「2024 年」限定不能删，`notion:company:2` 建议写成「CNBC 榜单列出的 3 位创始人」以避开 3 人 / 6 人口径争议。
`airbnb:company:0` 的 2007 vs 2008 **不是矛盾、是口径**：官方 About 写 2007 年首批房客（起源），
同页时间线写 2008-03 SXSW 正式上线、2008-08 网站上线；保留「起源于 2007 年」的措辞即可。

## B. 建议改了再用（8 条）

| id | 查出的问题 | 建议 |
|---|---|---|
| `figma:news:0` | 原出处是第三方公司目录（BrandLigo），虽逐字有那句话，但不是一手 | 换 [Adobe 官方联合声明](https://news.adobe.com/news/news-details/2023/Adobe-and-Figma-Mutually-Agree-to-Terminate-Merger-Agreement/default.aspx)，补精确日期 **2023-12-18** 与监管原因 |
| `figma:financial:0` | 上市月份各来源打架（7 月 vs 8 月） | **冲突已查清**：[Figma 官方 IPO 公告](https://www.figma.com/blog/ipo-pricing/) 写明 2025-07-31 开始交易、08-01 交割完成、发行价 $33、代码 FIG。改成官方口径 |
| `airbnb:financial:0` | 原文是 `expected to begin trading`（**预计**开始交易），草稿写成「已上市」，超出了该 URL 的证明范围 | 出处不变，事实改成「2020-12-09 定价公告宣布：发行价 $68、预计 12-10 在纳斯达克交易，代码 ABNB」 |
| `canva:company:0/1`、`canva:company:2/3`、`canva:industry:0` | 3 个 Business Wire 原始 URL（西/法/中文版）**全部返回 Page Unavailable**，无法核验 | 换可访问的 [2023-08-29 官方新闻稿全文转载](https://www.newswire.co.kr/newsRead.php?no=973123)（页脚给出 Business Wire 原稿链接）；5 条事实在该全文里逐字可查 |

## C. 建议删除或重做（2 条）

| id | 为什么不能留 | 建议 |
|---|---|---|
| `notion:financial:0` | 草稿那段「2021-10 / 2.75 亿 C 轮 / 100 亿→110 亿 tender」在 CNBC **2026 版和 2025 版全文里都不存在**（两次核对均 NOT FOUND），疑似来自更早版本或搜索摘要；页面实际字段是 Funding $330M / Valuation $11B（2026）、$10B（2025） | 删掉原事实，改为「CNBC 2025 榜单记录累计融资 3.3 亿美元、估值 100 亿美元（历史时点）」，URL 换 [2025 版](https://www.cnbc.com/2025/06/10/notion-cnbc-disruptor-50.html) |
| `airbnb:industry:0` | 原 URL `wikipedia.com` 抓取失败，且**该域名不是官方维基**（wikipedia.org），是镜像；「acts as a broker / 佣金」是维基措辞，官方未用 | 换 [Airbnb 官方服务费说明](https://www.airbnb.com/resources/hosting-homes/a/-288)，事实收敛为「每笔预订确认时收取服务费」；不要写「经纪商」「佣金」或具体费率（2026 年已改单一 15.5% 房东费） |

## 复核结论（如实）

- 9 个原始 URL 中 **3 个打不开**（2 个 Business Wire、`wikipedia.com`）。
- 8 条冲突里，**2 条已用官方一手来源彻底解决**（Figma IPO 月份、Airbnb 创立年份口径）；其余是时点/口径问题，已在证据表里写明保留限定的方式。
- **25 条里没有一条被标成 `human_verified`**。在 `user_verdict` 全部填完前，草稿与复核表都不得接入 `evals/run_eval.py`，也不得写进简历。
- 另有一处方法论边界（S8.4）：真实模型报告不会与 `candidate_fact` 逐字一致，S7 的精确文本匹配在真实语料上会全判 0 分，正式 golden 必须配语义 judge 或人工判定。
