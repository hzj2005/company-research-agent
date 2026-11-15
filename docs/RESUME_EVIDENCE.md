# 简历数字出处表（S8.6）

> **一句话**：这份表只收录「能当场复现」的数字，每条都给出值、出处文件 + 字段、该文件最后修改的 commit、以及一条可直接执行的复现命令。复现不了的一律不写。

**归因红线**：本项目基于 `guy-hartstein/company-research-agent`（Apache-2.0）二次开发，`LICENSE` 与上游 commit `23fe92d` 均保留；简历不得写「独立开发」，只写「本地实测」，不写甲方 / 上线 / 用户量。

```bash
uv run python -m evals.build_resume_evidence --verify   # 逐条执行复现命令并比对
uv run pytest -q tests/test_s8_resume_evidence.py      # 护栏：命令、commit、禁写清单
```

生成过程装 `eval_offline_guard`，本次实测拦截外部连接 **0** 次；本阶段 **0** 次模型请求、**0** Tavily credits。

## 1. 使用规则

- 只有在 §2 表里的数字才允许进入简历措辞，且必须带上其口径限定（例如 F11 只能写「单次墙钟」，不能写 p95）。
- `commit` 列是**录入时**该文件的最后一次修改提交，冻结在 `evals/resume_evidence_commits.json`，不随之后的新提交漂移；刷新台账用 `--record-commits`。它不是本文的提交，也不代表该数字首次出现的版本。
- 护栏会用 `git show <commit>:<文件>` 复核：**该数值在那个 commit 里确实存在**，比「最后一次修改」更接近简历要的语义；文档文件则只校验存在性。
- 复现命令从 (文件, 字段路径) 自动生成，代码里只 `json.load` / `open`，**不 import 本脚本、不联网**，因此可独立核验，不构成自证循环。
- 所有 credits 数字均为「按 Tavily 官方计费规则推算」，不是账单；本项目从未查询或记录真实扣费。

## 2. 可写进简历的数字

### 2.1 A 组｜真机一次端到端报告

样本：公司 `"Notion"`，`app_mode="live"`，真实报告 **1 份**（该文件只记录一次运行）。所有数字来自同一次运行，不得外推成总体表现。

| 编号 | 数字 | 值 | 出处（文件 → 字段） | commit | 复现命令 |
|---|---|---:|---|---|---|
| `F01` | 累计 Tavily credits | `8` | `evals/live_run.json` → `credits.cumulative` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["credits"]["cumulative"], ensure_ascii=False))'` |
| `F02` | 用户设定的 credits 硬上限 | `50` | `evals/live_run.json` → `credits.user_ceiling` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["credits"]["user_ceiling"], ensure_ascii=False))'` |
| `F03` | 本轮 credits | `6` | `evals/live_run.json` → `credits.spent_this_run` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["credits"]["spent_this_run"], ensure_ascii=False))'` |
| `F04` | 真实检索次数 | `3` | `evals/live_run.json` → `budget.calls_made` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["budget"]["calls_made"], ensure_ascii=False))'` |
| `F05` | 缓存命中次数 | `1` | `evals/live_run.json` → `budget.cache_hits` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["budget"]["cache_hits"], ensure_ascii=False))'` |
| `F06` | 模型请求次数 | `4` | `evals/live_run.json` → `llm_usage.successful_requests` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["llm_usage"]["successful_requests"], ensure_ascii=False))'` |
| `F07` | 模型 token 用量 | `7896` | `evals/live_run.json` → `llm_usage.total_tokens` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["llm_usage"]["total_tokens"], ensure_ascii=False))'` |
| `F08` | 报告字符数 | `4998` | `evals/live_run.json` → `report_checks.chars` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["report_checks"]["chars"], ensure_ascii=False))'` |
| `F09` | 参考文献条目 | `11` | `evals/live_run.json` → `report_checks.reference_lines` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["report_checks"]["reference_lines"], ensure_ascii=False))'` |
| `F10` | 正文行内引用标记 | `27` | `evals/live_run.json` → `report_checks.inline_citation_markers` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["report_checks"]["inline_citation_markers"], ensure_ascii=False))'` |
| `F11` | 单次墙钟耗时(ms) | `62875.8` | `evals/live_run.json` → `timing.elapsed_ms` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["timing"]["elapsed_ms"], ensure_ascii=False))'` |
| `F12` | dry-run 预算 query 数 | `12` | `evals/live_dryrun.json` → `budget.query_count` | `0d6247b` | `uv run python -c 'import json; d=json.load(open("evals/live_dryrun.json", encoding="utf-8")); print(json.dumps(d["budget"]["query_count"], ensure_ascii=False))'` |
| `F26` | 报告栏目数 | `4` | `evals/live_run.json` → `len(config.sections)` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(len(d["config"]["sections"]), ensure_ascii=False))'` |

### 2.2 B 组｜评测工程与数据可信度

| 编号 | 数字 | 值 | 出处（文件 → 字段） | commit | 复现命令 |
|---|---|---:|---|---|---|
| `F13` | 人工核验标准答案条数 | `25` | `evals/golden_live.jsonl` → `len([r for r in lines if r["kind"] == "claim"])` | `3e16906` | `uv run python -c 'import json; d=[json.loads(l) for l in open("evals/golden_live.jsonl", encoding="utf-8") if l.strip()]; print(json.dumps(len([r for r in d if r["kind"] == "claim"]), ensure_ascii=False))'` |
| `F14` | 覆盖公司数 | `5` | `evals/golden_live.jsonl` → `len({r["case"] for r in lines if r["kind"] == "claim"})` | `3e16906` | `uv run python -c 'import json; d=[json.loads(l) for l in open("evals/golden_live.jsonl", encoding="utf-8") if l.strip()]; print(json.dumps(len({r["case"] for r in d if r["kind"] == "claim"}), ensure_ascii=False))'` |
| `F15` | 用户二次修订条数 | `11` | `evals/golden_live.jsonl` → `0.claims_revised_by_user` | `3e16906` | `uv run python -c 'import json; d=[json.loads(l) for l in open("evals/golden_live.jsonl", encoding="utf-8") if l.strip()]; print(json.dumps(d[0]["claims_revised_by_user"], ensure_ascii=False))'` |
| `F16` | 替换掉的不可达原始 URL | `6` | `evals/golden_live.jsonl` → `0.original_unreachable_source_urls` | `3e16906` | `uv run python -c 'import json; d=[json.loads(l) for l in open("evals/golden_live.jsonl", encoding="utf-8") if l.strip()]; print(json.dumps(d[0]["original_unreachable_source_urls"], ensure_ascii=False))'` |
| `F17` | 真机可比对条数 | `5` | `evals/live_score.json` → `dataset.scored_claims` | `3e16906` | `uv run python -c 'import json; d=json.load(open("evals/live_score.json", encoding="utf-8")); print(json.dumps(d["dataset"]["scored_claims"], ensure_ascii=False))'` |
| `F18` | 因无报告而跳过的条数 | `20` | `evals/live_score.json` → `dataset.skipped_claims` | `3e16906` | `uv run python -c 'import json; d=json.load(open("evals/live_score.json", encoding="utf-8")); print(json.dumps(d["dataset"]["skipped_claims"], ensure_ascii=False))'` |
| `F19` | 语义 judge 请求次数 | `1` | `evals/live_score.json` → `usage.successful_requests` | `3e16906` | `uv run python -c 'import json; d=json.load(open("evals/live_score.json", encoding="utf-8")); print(json.dumps(d["usage"]["successful_requests"], ensure_ascii=False))'` |
| `F20` | 语义 judge token 用量 | `2776` | `evals/live_score.json` → `usage.total_tokens` | `3e16906` | `uv run python -c 'import json; d=json.load(open("evals/live_score.json", encoding="utf-8")); print(json.dumps(d["usage"]["total_tokens"], ensure_ascii=False))'` |
| `F21` | 审计重算差异条数 | `0` | `evals/live_score_audit.json` → `len(recheck.delta_vs_original)` | `9041beb` | `uv run python -c 'import json; d=json.load(open("evals/live_score_audit.json", encoding="utf-8")); print(json.dumps(len(d["recheck"]["delta_vs_original"]), ensure_ascii=False))'` |
| `F22` | fixture 评测组总数 | `6` | `evals/scorecard.json` → `len(summary.groups_run)` | `55f24cb` | `uv run python -c 'import json; d=json.load(open("evals/scorecard.json", encoding="utf-8")); print(json.dumps(len(d["summary"]["groups_run"]), ensure_ascii=False))'` |
| `F27` | 评测指标项数 | `8` | `evals/scorecard.json` → `len(runs.baseline.metrics)` | `55f24cb` | `uv run python -c 'import json; d=json.load(open("evals/scorecard.json", encoding="utf-8")); print(json.dumps(len(d["runs"]["baseline"]["metrics"]), ensure_ascii=False))'` |
| `F28` | fixture 用例数 | `3` | `evals/scorecard.json` → `runs.baseline.counts.cases` | `55f24cb` | `uv run python -c 'import json; d=json.load(open("evals/scorecard.json", encoding="utf-8")); print(json.dumps(d["runs"]["baseline"]["counts"]["cases"], ensure_ascii=False))'` |
| `F29` | fixture 标准答案条数 | `23` | `evals/scorecard.json` → `runs.baseline.counts.expected_claims` | `55f24cb` | `uv run python -c 'import json; d=json.load(open("evals/scorecard.json", encoding="utf-8")); print(json.dumps(d["runs"]["baseline"]["counts"]["expected_claims"], ensure_ascii=False))'` |

### 2.3 C 组｜额度纪律

| 编号 | 数字 | 值 | 出处（文件 → 字段） | commit | 复现命令 |
|---|---|---:|---|---|---|
| `F23` | fixture 回归外部 Tavily 调用 | `0` | `evals/scorecard.json` → `external_calls.tavily` | `55f24cb` | `uv run python -c 'import json; d=json.load(open("evals/scorecard.json", encoding="utf-8")); print(json.dumps(d["external_calls"]["tavily"], ensure_ascii=False))'` |
| `F24` | 语义 judge 的 Tavily 调用 | `0` | `evals/live_score.json` → `isolation.tavily_client_search_calls` | `3e16906` | `uv run python -c 'import json; d=json.load(open("evals/live_score.json", encoding="utf-8")); print(json.dumps(d["isolation"]["tavily_client_search_calls"], ensure_ascii=False))'` |
| `F25` | 最小真实探针 credits | `2` | `evals/live_probe.json` → `credits.estimated_credits_used` | `55f24cb` | `uv run python -c 'import json; d=json.load(open("evals/live_probe.json", encoding="utf-8")); print(json.dumps(d["credits"]["estimated_credits_used"], ensure_ascii=False))'` |
| `F31` | 单次 advanced 检索计费 | `2` | `evals/live_run.json` → `credits.credits_per_search` | `53746f6` | `uv run python -c 'import json; d=json.load(open("evals/live_run.json", encoding="utf-8")); print(json.dumps(d["credits"]["credits_per_search"], ensure_ascii=False))'` |
| `F30` | S8 累计真实模型请求 | `6` | `evals/llm_probe.json` + `evals/live_run.json` + `evals/live_score.json` → `llm_probe + live_run + live_score 三处求和` | `53746f6` / `53746f6` / `3e16906` | `uv run python -c 'import json; d0=json.load(open("evals/llm_probe.json", encoding="utf-8")); d1=json.load(open("evals/live_run.json", encoding="utf-8")); d2=json.load(open("evals/live_score.json", encoding="utf-8")); print(json.dumps(d0["usage"]["successful_requests"]+d1["llm_usage"]["successful_requests"]+d2["usage"]["successful_requests"], ensure_ascii=False))'` |

### 2.4 D 组｜批量真实调研（S10-B）

样本：4 家公司、20 条人工核验标准答案（用户逐条复核）；额度以 `evals/credits_ledger.json` 为准，累计 50。这批数据是 S10 修复后重跑的，与 A 组的单家报告不可混算。

| 编号 | 数字 | 值 | 出处（文件 → 字段） | commit | 复现命令 |
|---|---|---:|---|---|---|
| `F32` | 批量真实调研公司数 | `4` | `evals/live_batch.json` → `len(companies)` | `b1fdc84` | `uv run python -c 'import json; d=json.load(open("evals/live_batch.json", encoding="utf-8")); print(json.dumps(len(d["companies"]), ensure_ascii=False))'` |
| `F33` | 可批改标准答案条数 | `20` | `evals/live_score_batch.json` → `aggregate.scored_claims` | `b1fdc84` | `uv run python -c 'import json; d=json.load(open("evals/live_score_batch.json", encoding="utf-8")); print(json.dumps(d["aggregate"]["scored_claims"], ensure_ascii=False))'` |
| `F34` | 判为支持的条数 | `8` | `evals/live_score_batch.json` → `aggregate.supported` | `b1fdc84` | `uv run python -c 'import json; d=json.load(open("evals/live_score_batch.json", encoding="utf-8")); print(json.dumps(d["aggregate"]["supported"], ensure_ascii=False))'` |
| `F35` | 判为反证的条数 | `2` | `evals/live_score_batch.json` → `aggregate.refuted` | `b1fdc84` | `uv run python -c 'import json; d=json.load(open("evals/live_score_batch.json", encoding="utf-8")); print(json.dumps(d["aggregate"]["refuted"], ensure_ascii=False))'` |
| `F36` | 判为未提及的条数 | `10` | `evals/live_score_batch.json` → `aggregate.not_mentioned` | `b1fdc84` | `uv run python -c 'import json; d=json.load(open("evals/live_score_batch.json", encoding="utf-8")); print(json.dumps(d["aggregate"]["not_mentioned"], ensure_ascii=False))'` |
| `F37` | 引文校验失败条数 | `0` | `evals/live_score_batch.json` → `aggregate.quote_check_failed` | `b1fdc84` | `uv run python -c 'import json; d=json.load(open("evals/live_score_batch.json", encoding="utf-8")); print(json.dumps(d["aggregate"]["quote_check_failed"], ensure_ascii=False))'` |
| `F38` | Tavily credits 累计 | `50` | `evals/credits_ledger.json` → `total_credits` | `6a0a412` | `uv run python -c 'import json; d=json.load(open("evals/credits_ledger.json", encoding="utf-8")); print(json.dumps(d["total_credits"], ensure_ascii=False))'` |
| `F39` | 实体消歧拒绝篇次 | `4` | `evals/live_batch.json` → `summary.entity_guard_rejections` | `b1fdc84` | `uv run python -c 'import json; d=json.load(open("evals/live_batch.json", encoding="utf-8")); print(json.dumps(d["summary"]["entity_guard_rejections"], ensure_ascii=False))'` |

## 3. 简历可用措辞（按编号）

**真机实测**

- `F01` 在累计 8 credits 的预算内完成端到端真实调研（按官方计费规则推算，非账单）
  - 边界：含 S8.2 单次探针；按官方 advanced=2 credits/次推算，非扣费账单
- `F02` 为用户额度设 50 credits 硬上限，全程未突破
  - 边界：上限是用户放行值，不是 Tavily 免费额度总量
- `F03` 单次报告消耗 6 credits
  - 边界：按 `budget.calls_made` × `credits.credits_per_search` 推算；缓存命中不扣
- `F04` 单次调研发起 3 次真实联网检索
  - 边界：CallBudget 记录的生产路径调用数
- `F05` 引入 sha256 检索缓存，单次运行命中 1 次
  - 边界：命中不产生额度消耗
- `F06` 单次报告完成 4 次大模型请求
  - 边界：get_openai_callback 捕获；不含 S8.4 judge 的请求
- `F07` 单次报告消耗 7896 tokens
  - 边界：真实计数；但单价未知，不换算成本
- `F08` 产出 4998 字符的四栏目带引用简报
  - 边界：词法统计，不代表内容质量
- `F09` 简报附 11 条参考来源
  - 边界：仅为条目数，引用可追溯率未测
- `F10` 正文含 27 处行内引用标记
  - 边界：只数 ## References 之前的正文；不代表引用正确
- `F11` 单次端到端墙钟 62875.8 ms（**不是 p95**）
  - 边界：含网络往返，非确定性字段；不得写成 p95 / 平均延迟
- `F12` 0 调用预演出完整调研最多会发 12 条 query
  - 边界：预算推算，非真实请求；真实检索次数见 F04
- `F26` 输出 4 个固定栏目（Company / Industry / Financial / News）
  - 边界：栏目结构固定；每栏内容质量另见 F17 / F18 的批改口径

**评测工程**

- `F13` 构建 25 条人工核验的事实标准答案
  - 边界：事实层经用户逐条复核；引用层未核验
- `F14` 标准答案覆盖 5 家公司
  - 边界：其中仅 `live_run.company` 一家有真实报告；可对答案的条数见 F17
- `F15` 二次复核修订 11 条最终标准答案
  - 边界：正式 golden 同时保留草稿版与最终版，可追溯改动
- `F16` 复核发现并替换 6 条打不开的原始出处
  - 边界：新 URL 未在本项目内重新抓取，引用层仍不可算指标
- `F17` 语义批改实际比对 5 条事实
  - 边界：样本仅为 `live_run.company` 一家一份报告，不代表整体准确率
- `F18` 20 条标准答案如实跳过（无对应真实报告，不编造）
  - 边界：体现评测口径纪律，不是漏测
- `F19` AI 语义批改链路由 1 次模型请求完成
  - 边界：如实标 AI judge 非人工裁定，不作为简历指标
- `F20` 语义批改消耗 2776 tokens
  - 边界：单价未知，不换算成本
- `F21` 评测链路修复后事后审计重算差异 0 条
  - 边界：0 差异代表修复未改变既有判定，不代表判定正确
- `F22` 评测台内置 6 个评测组（含 baseline 与开关 A/B 组）
  - 边界：fixture 合成语料，测流程契约不测真实效果；除 baseline 外才是 A/B 对照
- `F27` 评测台覆盖 8 项指标
  - 边界：fixture 合成语料；指标定义见 `evals/metrics.py`，不代表真机效果
- `F28` fixture 回归覆盖 3 个用例场景
  - 边界：合成语料，只测流程契约；真实样本见 F13 / F14
- `F29` fixture 集含 23 条标准 claim
  - 边界：合成语料；人工核验的真实 golden 见 F13

**额度纪律**

- `F23` fixture 契约回归全程 0 次外部检索
  - 边界：禁网守卫保证回归不会误耗额度
- `F24` 语义批改环节 0 次检索
  - 边界：judge 只读本地报告；额度消耗见 `isolation.tavily_credits_used`
- `F25` 用 2 credits 的最小探针坐实真实检索返回结构
  - 边界：按官方规则推算；真实累计见 F01
- `F31` 按官方计费规则，每次 advanced 检索计 2 credits
  - 边界：官方规则推算，不是账单；缓存命中不扣
- `F30` S8 阶段累计 6 次真实模型请求（兼容性探针 + 端到端报告 + 语义批改）
  - 边界：分项见 F06 / F19 与 `evals/llm_probe.json`；成本仍 null

**批量真实调研**

- `F32` 一次批量真实调研覆盖 4 家公司
  - 边界：Notion 复用 S8.3 磁盘缓存（0 credits），其余为新检索
- `F33` 把 20 条人工核验标准答案全部对上真实报告
  - 边界：全部经用户逐条复核；引用层仍未核验，不是准确率的分母
- `F34` 其中 8 条被报告完整支持
  - 边界：supported 只表示报告里有这句话，不代表来源 URL 真的支持它
- `F35` 2 条被判为与标准答案矛盾
  - 边界：含 judge 口径偏严的情形（见 `docs/LIVE_BATCH.md` §5），不等于系统答错
- `F36` 10 条报告未写到
  - 边界：未提及不等于答错；把它算错或排除会得到两个都不该叫准确率的数
- `F37` 批改的引文逐字校验失败 0 条
  - 边界：0 说明每条判定都有可核到的原文证据，不是模型凭印象编的
- `F38` 全部真实检索累计 50 credits（含一次失败重跑的损失）
  - 边界：台账在 `evals/credits_ledger.json`；失败的运行也照记
- `F39` 实体消歧在真实数据上触发 4 次拒绝
  - 边界：是「篇次」不是「篇数」：2 篇不同文档各被首轮与补搜两次判定

> 措辞里出现的每个数值都由对应编号的字段插值生成；别把两个编号的数字拼成一句未经验证的复合指标（例如「准确率」「提升」）。

## 4. 禁写清单（同样给出处）

| 禁止写法 | 事实 | 出处 | 为什么 |
|---|---|---|---|
| ❌「准确率 100% / 效果好」 | fixture `fact_accuracy` 是合成语料契约回归分 | `evals/scorecard.json` → `runs.baseline.metrics.fact_accuracy` 〔`55f24cb`〕 | 关开关就会变，测的是流程不是效果 |
| ❌「p95 延迟 X ms」 | fixture `p95_latency_ms` 是本机合成语料耗时 | `evals/scorecard.json` → `runs.baseline.metrics.p95_latency_ms` 〔`55f24cb`〕 | 0 外部调用；真机 p95 未测 |
| ❌「零成本 / 每份 X 元」 | fixture `cost_per_report` 与真机 `total_cost_usd` 均不可当成本 | `evals/scorecard.json` → `runs.baseline.metrics.cost_per_report` 〔`55f24cb`〕 | 真机 `evals/live_run.json` → `llm_usage.total_cost_usd` 为 null 〔`53746f6`〕；qwen-plus 单价不在价目表内 |
| ❌「幻觉率 0%」 | fixture `hallucination_rate` 只反映词法代理 | `evals/scorecard.json` → `runs.baseline.metrics.hallucination_rate` 〔`55f24cb`〕 | 引用层未核验，真机幻觉率未测 |
| ❌「准确率 0%（因为 supported=0）」 | AI judge 的 supported 计数是极少量样本的判定分布 | `evals/live_score.json` → `summary.supported` 〔`3e16906`〕 | `usable_as_resume_metric=false`、`is_human_adjudicated=false` |
| ❌ 把 judge 结果写成人工评测指标 | judge 是 AI 判定，未经人工抽检一致率校准 | `evals/live_score.json` → `is_human_adjudicated` 〔`3e16906`〕 | 样本见 F17 / F18，另有措辞瑕疵记录 |
| ❌「独立开发 / 从零自研」 | 本项目基于上游仓库二次开发（Apache-2.0） | `docs/UPSTREAM.md` → 落地 commit 〔`6e7ce22`〕；根目录 `LICENSE` 〔`23fe92d`〕 | 必须保留 LICENSE 与上游 commit 归因 |
| ❌「上线 / 甲方 / 用户量 / 效果提升 X%」 | 本项目是本地个人工程复现，无这些事实 | `docs/ACTION_PLAN.md` → 12.3 硬约束 〔`6a0a412`〕 | 简历只写「本地实测」 |
| ❌「引用可追溯率 X%」 | 最终 URL 多数未在本项目内重新抓取核验 | `evals/golden_live.jsonl` → `0.citation_layer_usable_as_metric` 〔`3e16906`〕 | 引用层指标明确不可用 |

## 5. 未测清单（一律不得写进简历）

- 真实准确率、幻觉率、引用可追溯率、p95 延迟、成本单价：**未测**。
- 依据：`evals/live_score.json` → `metric_boundary` 〔`3e16906`〕；`evals/live_run.json` → `llm_usage.total_cost_usd` 为 `null` 〔`53746f6`〕。
- 完整对比见 `docs/LIVE_REPORT.md` 〔`6fb301e`〕；fixture 侧有值、真机侧未测，两者不可相减。
- 累计额度仍为 `8` / `50` credits；本阶段未新增任何调用。

## 6. 复现机制

1. `evals/build_resume_evidence.py` 的 `Fact` 持有 `key/path`；`expr_from_path()` 把同一路径翻译成 `d["a"]["b"]`，拼成独立的 `python -c` 命令。
2. `--verify` 对每条数字**真的起一个进程执行该命令**，把 stdout 与产物取值逐字比对（两边都用 `json.dumps`，bool/null 不会走样）。
3. `tests/test_s8_resume_evidence.py` 再做一遍同样的事，并逐条用 `git show <commit>:<文件>` 回到台账标注的版本重算该字段——「这个数字在那个 commit 里就有」能被机器验证，而不只是写着一行 hash。
4. 当前共 **39** 条可复现数字、**9** 条禁写规则；这两个计数也由列表长度生成，不是手填。

## 7. 状态

- 本文生成：**0** 次外部连接、**0** 次模型请求、**0** Tavily credits。
- **S9 已完成**：`docs/RESUME.md` 的每条描述都按本表编号插值，`tests/test_s9_resume.py` 校验「简历里出现的每个数字都来自本表」。
- 真实效果指标仍为未测；本表只保证「写出来的数字查得到」，不保证「系统效果好」。
