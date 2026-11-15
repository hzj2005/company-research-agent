# S10-B 批量真实调研：4 家公司 / 20 条人工核验标准答案

> 一句话：把已经人工核验过的 **20 条**标准答案第一次全部对上了**真实报告**。
> 结果 **8 条支持 / 2 条反证 / 10 条未提及**，0 条未判定、0 条引文造假。
> **这不是准确率**：未提及不等于答错，被判反证的 2 条里至少 1 条是 judge 口径偏严。
>
> 生成：2026-11-15。原始产物 `evals/live_batch.json`（报告）、
> `evals/live_score_batch.json`（判定）。本文每个数字都能由这两个文件当场复核。

## 1. 花了多少

| 项 | 值 | 依据 |
|---|---|---|
| 公司数 | **4**（Notion / Figma / Stripe / Airbnb） | `live_batch.json: companies` |
| Tavily 真实请求 | **5 次**（Stripe 4 + Notion 补搜 1） | `live_batch.json: budget.calls_made` |
| 缓存命中 | **12 次**（Notion 首轮 4 + Figma 4 + Airbnb 4） | 同上 `cache_hits` |
| Tavily credits | **+10**（advanced = 2/次） | `live_batch.json: credits.spent_this_run` |
| 累计 credits | **42 / 50** | 同上 `cumulative` / `user_ceiling` |
| 模型请求 | **20 次**（16 次抽取 + 4 次批改），41813 tokens | `live_batch.json: runs[].llm_usage`、`live_score_batch.json: companies[].usage` |
| 耗时 | 跑批 **164 s** / 批改 **48 s** | 两份产物的 `timing` / `elapsed_ms` |

**为什么只花 10 credits 就跑了 4 家**：Notion 的 4 条 query 与 S8.3 完全一致，
Figma / Airbnb 的 4 条在上一轮已经写进磁盘缓存，命中不扣额度。真金白银只花在
**Stripe 的 4 次检索**和 **Notion 的 1 次补搜**上。

## 2. 四份报告长什么样

| 公司 | 字符 | 引用条数 | 四栏目齐全 | 实体消歧拒绝 | 模型 tokens |
|---|---|---|---|---|---|
| Notion | 3971 | 11 | 是 | **4**（2 条不同文档 × 两轮） | 7439 |
| Figma | 3847 | 12 | 是 | 0 | 8509 |
| Stripe | 4573 | 11 | 是 | 0 | 7835 |
| Airbnb | 4441 | 12 | 是 | 0 | 8152 |

四家都**没有触发降级**（`degraded_sections` 为空）；Notion 的 `company` 栏目因为
消歧拒掉 1 篇后掉到证据下限，触发了 1 次补搜（`retry_count={"company": 1}`）——
补搜后候选从 3 篇变 5 篇，那篇 `notion.online` **仍然被判异实体**。这一点比首轮命中
更有价值：规则不是记住了某个标题，而是换一批文档照样能判。

## 3. 判定明细（20 条）

| # | claim_id | 标准答案（摘要） | 判定 |
|---|---|---|---|
| 1 | `notion:company:0` | 2013 年创办 | **supported** |
| 2 | `notion:company:1` | 总部旧金山 | **supported** |
| 3 | `notion:company:2` | 创始人含 Ivan Zhao | **supported** |
| 4 | `notion:industry:0` | 模块化协作工作区 | not_mentioned |
| 5 | `notion:financial:0` | 2021-10 完成 2.75 亿美元融资 | **supported** |
| 6 | `figma:company:0` | 成立于 2012 年 | **supported** |
| 7 | `figma:company:1` | Dylan Field 是联合创始人兼 CEO | not_mentioned |
| 8 | `figma:industry:0` | 从设计工具演进为端到端平台 | not_mentioned |
| 9 | `figma:news:0` | Adobe 与 Figma 2023-12 终止合并 | not_mentioned |
| 10 | `figma:financial:0` | 2025-07-31 在纽交所上市 | **refuted**（口径可争议，见 §5） |
| 11 | `stripe:industry:0` | 为互联网构建经济基础设施 | not_mentioned |
| 12 | `stripe:company:0` | 旧金山 + 都柏林双总部 | **refuted**（口径可争议，见 §5） |
| 13 | `stripe:company:1` | Patrick Collison 联合创始人兼 CEO | **supported** |
| 14 | `stripe:company:2` | John Collison 联合创始人兼总裁 | **supported** |
| 15 | `stripe:financial:0` | 2024 年处理支付额超 1 万亿美元 | not_mentioned |
| 16 | `airbnb:company:0` | 2007 年起源于旧金山气垫床 | not_mentioned |
| 17 | `airbnb:company:1` | 三位创始人姓名 | not_mentioned |
| 18 | `airbnb:company:2` | 2009-03 更名 Airbed & Breakfast | not_mentioned |
| 19 | `airbnb:financial:0` | 2020-12-09 发行价 68 美元 | not_mentioned |
| 20 | `airbnb:industry:0` | 连接房东与旅客的在线住宿平台 | **supported** |

**汇总**：supported **8** / refuted **2** / not_mentioned **10** / unjudged **0** /
`quote_check_failed` **0**。

`quote_check_failed=0` 值得单独说：judge 给出的每条证据句都在报告正文里**逐字**找到了，
说明这些判定不是模型凭印象编的（校验口径见 `docs/LIVE_SCORE.md` §2）。

## 4. 修复前后同题对比：Notion

同一个 `golden_live.jsonl`、同一家公司的 5 条标准答案，前后两次判定的差别：

| claim_id | 修复前（S8.4，`live_score.json`） | 修复后（本轮） |
|---|---|---|
| `notion:company:0` 2013 年创办 | **refuted**（报告同时写了 2013 和 2014） | **supported** |
| `notion:company:1` 总部旧金山 | not_mentioned（报告写成伦敦门牌） | **supported** |
| `notion:company:2` 创始人 | not_mentioned | **supported** |
| `notion:industry:0` 模块化工作区 | not_mentioned | not_mentioned（仍然没写到） |
| `notion:financial:0` 2.75 亿美元融资 | **refuted**（Financial 整栏是 VTec 股价） | **supported** |
| **合计** | **0 / 2 / 3** | **4 / 0 / 1** |

修复后的报告里，三类硬伤全部消失：
- Company 栏目只剩 `Notion was founded in 2013.`，没有 2014 与之打架；
- 总部变成 `Notion Labs, Inc. was founded in San Francisco, California.`，伦敦门牌随 `notion.online` 那篇一起被拒；
- Financial 栏目从 10 条 VTec 股价指标变成 2 条真事实（20 亿、100 亿美元估值）。

**但这不等于「准确率从 0 变成 80%」**：两次跑的检索语料不完全相同（本轮 Notion 多了一次
补搜），而且样本只有 5 条。能说的只有一句：**同样的 5 个问题，修复后被完整支持 4 条、
被判错 0 条；修复前是支持 0 条、判错 2 条。**

## 5. 两条 refuted 的人工判读（不能直接当系统错）

judge 的 prompt 规定「报告有明确陈述与标准答案矛盾 → refuted」。按这个口径它判得没错，
但人工看下来这两条属于**边界**：

| claim | 报告写了什么 | 标准答案要求 | 判读 |
|---|---|---|---|
| `figma:financial:0` | "Figma completed its IPO in **July 2025** … stock symbol is **FIG**" | "2025-07-31 在**纽交所**上市" | 年月对得上，缺的是具体日期和交易所。按「细节没写全」看更像 not_mentioned，按「给了不完整的明确陈述」看是 refuted。**偏严。** |
| `stripe:company:0` | "Stripe is headquartered in **San Francisco**, California, US." | "旧金山和都柏林**双总部**" | 报告只写了其中一个，没有否认另一个。判 refuted 等于把「没说全」当成「说反了」。**偏严。** |

结论：**2/20 的 refuted 里，至少 1 条（很可能 2 条）是 judge 口径偏严，不是系统答错。**
真实答错率比 2/20 更低，但具体是多少，必须人工逐条判才算数 —— 本文不做这个推断。

## 6. 真正暴露的问题：从「说错」变成「没说」

修复前 Notion 的问题是**硬伤**（数据来自别的公司、自相矛盾）。修复后 20 条里
`not_mentioned` 占 **10 条（50%）**，说明瓶颈换了一个：

- Airbnb 5 条里 4 条没写到 —— 报告只有 4441 字符、12 条引用，Company 栏目没有覆盖创业史；
- Figma 3 条没写到 —— 2023 年 Adobe 合并失败这类「关键历史」没进报告；
- Stripe 的「2024 年处理支付额超 1 万亿美元」也没写到。

这是**检索召回与栏目分配**的问题（4 个栏目各 1 条 query、每栏目最多 10 条结论），
不是实体消歧能解决的。要提升得改检索策略，会再花 credits。

## 7. 如实边界

- **`supported_share = 0.4` 是「标准答案被完整支持的比例」，不是准确率。**
  `not_mentioned` 占一半，把它算成「错」会得到 0.4，把它排除会得到 0.8 —— 两个数都不该叫准确率。
- **5 家公司不是随机抽样**，都是从黄金集里挑的知名公司，不能外推成「系统在任意公司上的表现」。
- **judge 是 AI，不是人工评分**。`is_human_adjudicated=false`，未经人工抽检一致率校准；
  本文 §5 已经示范了它会偏严。
- **引用层仍未核验**：`supported` 只表示「报告里有这句话」，不表示「这句话的 URL 真的支持它」。
- **成本单价仍是 `null`**：`qwen-plus` 不在 OpenAI 价目表内，不套用、不编造。

## 8. 复现命令

```bash
# 1) 批量真实调研（会花 Tavily credits，脚本自带全局预算与累计台账）
export DASHSCOPE_API_KEY="$SYSTEM_ALIYUN_APIKEY"
uv run python -m evals.batch_live Notion Figma Stripe Airbnb

# 2) 批量语义批改（只花模型请求，0 Tavily）
JUDGE_LIVE=1 uv run python -m evals.judge_batch --live

# 3) 只看不跑：确认候选与预算
uv run python -c "from evals import batch_live as b; print(b.DEFAULT_COMPANIES, b.credits_already_spent())"
```

⚠️ `evals/live_batch_v1.json` 与 `evals/live_score_batch_v1.json` 是**失败的第一次尝试**，
保留是为了如实记账：v1 把 `asyncio.run` 放在 for 循环里，第 2 家直接
`Event loop is closed`，Stripe 的 4 次检索发出去了却没拿到报告 —— 那 8 credits 是真实损失，
所以计入累计。修复方式是**整批共用一个事件循环**，串行 `await`。
