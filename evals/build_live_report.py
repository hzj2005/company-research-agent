"""S8.5：生成「fixture 契约回归 vs 真机表现」对比表 docs/LIVE_REPORT.md。

    uv run python -m evals.build_live_report

设计红线（对应 ACTION_PLAN 12.13）：

1. **只读取 6 份既有产物**，不跑模型、不跑 Tavily、不重算评测、不生成新指标；
   生成过程装 `eval_offline_guard`，任何外部连接都会抛错而非消耗额度。
2. **模板里不写死任何数字**：每个数值由 `Cell` 携带 `key/path/value`，
   `tests/test_s8_live_report.py` 会按路径从原始产物重算一遍。
3. **fixture 与真机不可比**：fixture 侧是合成语料 + 0 外部调用的契约回归分，
   真机侧是单次运行观察；两侧数字只并排展示，不相减、不换算成「提升/下降」。
4. 产物是文档，不是指标：`usable_as_resume_metric` 的边界沿用
   `evals/live_score.json`，真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价
   一律写「未测」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "LIVE_REPORT.md"

FILES: dict[str, str] = {
    "scorecard": "evals/scorecard.json",
    "live_run": "evals/live_run.json",
    "live_quality": "evals/live_quality.json",
    "live_score": "evals/live_score.json",
    "audit": "evals/live_score_audit.json",
    "dryrun": "evals/live_dryrun.json",
}

NOT_MEASURED = "未测"


def load_inputs() -> dict[str, Any]:
    """只读加载 6 份产物；缺文件直接报错，不静默 fallback。"""
    return {
        key: json.loads((ROOT / rel).read_text(encoding="utf-8"))
        for key, rel in FILES.items()
    }


def field(doc: Any, dotted: str) -> Any:
    """按点路径取值，支持 `a.b[0].c` 形式的列表索引。

    与文档里打印的出处路径共用同一套解析，避免「写出来的路径」和「实际取值的路径」脱节。
    """
    cur = doc
    for part in dotted.replace("[", ".").replace("]", "").split("."):
        if part.isdigit() and isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(f"字段不存在：{dotted}（停在 {part!r}）")
    return cur


@dataclass(frozen=True)
class Cell:
    """表格里的一个值 + 它的可重算出处。

    value 为 None 表示这不是一个数值（例如「未测」或定性描述），不参与重算；
    transform 用于「从 report 正文统计词频」这类派生值，测试会用同样的函数复核。
    """

    text: str
    ref: str = ""
    value: Any = None
    key: str = ""
    path: str = ""
    transform: Callable[[Any], Any] | None = None


def show(value: Any) -> str:
    """布尔按 JSON 风格显示（true/false），其余保持原值字符串。"""
    if isinstance(value, bool):
        return json.dumps(value)
    return str(value)


def num(data: dict[str, Any], key: str, path: str) -> Cell:
    """从产物字段取数值，出处直接由 FILES + path 生成。"""
    value = field(data[key], path)
    return Cell(
        text=show(value),
        ref=f"`{FILES[key]}` → `{path}`",
        value=value,
        key=key,
        path=path,
    )


def derived(data: dict[str, Any], key: str, path: str, label: str, fn: Callable[[Any], Any]) -> Cell:
    """派生数值（如正文里某个实体名出现次数），出处标明是派生而非原字段。"""
    raw = field(data[key], path)
    value = fn(raw)
    return Cell(
        text=show(value),
        ref=f"`{FILES[key]}` → `{path}`（{label}）",
        value=value,
        key=key,
        path=path,
        transform=fn,
    )


def note(text: str, data: dict[str, Any], key: str, path: str) -> Cell:
    """非数值单元格，但仍带证据出处。"""
    field(data[key], path)  # 路径写错就立刻报错，不生成一份查无实据的文档
    return Cell(text=text, ref=f"`{FILES[key]}` → `{path}`")


def ref_of(key: str, path: str) -> str:
    return f"`{FILES[key]}` → `{path}`"


@dataclass(frozen=True)
class Row:
    metric: str
    fixture: Cell
    live: Cell
    note: str


def comparison_rows(data: dict[str, Any]) -> list[Row]:
    """核心对比表：fixture 的 8 个指标，逐项写清真机侧到底测没测。"""
    s = data["live_score"]
    judge_requests = field(s, "usage.successful_requests")
    not_measured = lambda: note(NOT_MEASURED, data, "live_score", "metric_boundary.must_not_be_called")  # noqa: E731

    scored = field(s, "dataset.scored_claims")
    supported = field(s, "summary.supported")
    refuted = field(s, "summary.refuted")
    missing = field(s, "summary.not_mentioned")
    skipped = field(s, "dataset.skipped_claims")

    return [
        Row(
            "事实准确率 `fact_accuracy`",
            num(data, "scorecard", "runs.baseline.metrics.fact_accuracy"),
            not_measured(),
            f"真机侧只有 {scored} 条 AI 判定明细（supported={supported} / refuted={refuted} / "
            f"not_mentioned={missing}），另有 {skipped} 条没有卷子可比；判定明细不是准确率。",
        ),
        Row(
            "引用可追溯 `citation_traceability`",
            num(data, "scorecard", "runs.baseline.metrics.citation_traceability"),
            not_measured(),
            "fixture 侧是词法包含代理判定；golden 的最终 URL 是否支撑事实未核验，引用层不能出分。",
        ),
        Row(
            "幻觉率 `hallucination_rate`",
            num(data, "scorecard", "runs.baseline.metrics.hallucination_rate"),
            not_measured(),
            "真机报告确有事实错与实体混淆，但没有人工判定的幻觉样本统计，不能换算成比率。",
        ),
        Row(
            "p95 延迟 `p95_latency_ms`",
            num(data, "scorecard", "runs.baseline.metrics.p95_latency_ms"),
            not_measured(),
            f"fixture 数值是合成语料上的本机墙钟；真机只有单次 "
            f"{field(data['live_run'], 'timing.elapsed_ms')} ms 墙钟，不是 p95。",
        ),
        Row(
            "单份成本 `cost_per_report`",
            num(data, "scorecard", "runs.baseline.metrics.cost_per_report"),
            not_measured(),
            "fixture 侧 0 外部调用故为 0；真机 `llm_usage.total_cost_usd` 为 null，qwen-plus 单价不套用、不编造。",
        ),
        Row(
            "拒答率 `abstain_rate`",
            num(data, "scorecard", "runs.baseline.metrics.abstain_rate"),
            not_measured(),
            "fixture 有专门的拒答样本；真机单次报告 `report_checks.abstain_markers` 为 "
            f"{field(data['live_run'], 'report_checks.abstain_markers')}，不构成拒答率统计。",
        ),
        Row(
            "自纠正成功 `self_correction_success`",
            num(data, "scorecard", "runs.baseline.metrics.self_correction_success"),
            not_measured(),
            "真机首轮四个栏目都判 sufficient，`graph.retry_count` 为空，自纠正路径未触发。",
        ),
        Row(
            "平均重试轮次 `avg_retry_rounds`",
            num(data, "scorecard", "runs.baseline.metrics.avg_retry_rounds"),
            not_measured(),
            "同上：真机未触发重试，没有可统计的轮次样本。",
        ),
        Row(
            "LLM 请求数（同一阶段累计口径不同，仅作事实对照）",
            num(data, "scorecard", "external_calls.llm"),
            num(data, "live_run", "llm_usage.successful_requests"),
            f"fixture 是产物声明的 {field(data['scorecard'], 'external_calls.llm')} 调用；"
            f"真机是端到端一份报告的完成请求数，不含 S8.4 judge 的那 {judge_requests} 次。",
        ),
        Row(
            "Tavily 请求数",
            num(data, "scorecard", "external_calls.tavily"),
            num(data, "live_run", "budget.calls_made"),
            "fixture 0 调用；真机另有 1 次磁盘缓存命中，缓存不扣额度。",
        ),
    ]


def context_rows(data: dict[str, Any]) -> list[tuple[str, Cell, Cell]]:
    """§1 口径差异表：两侧根本不是同一种测量。"""
    c = lambda key, path: num(data, key, path)  # noqa: E731
    return [
        (
            "语料",
            note("合成 fixture", data, "scorecard", "provenance"),
            note("真实网页检索结果", data, "live_run", "config.app_mode"),
        ),
        (
            "样本规模",
            c("scorecard", "runs.baseline.counts.cases"),
            note(
                f"仅 `{field(data['live_run'], 'company')}` 一份真实报告",
                data, "live_run", "company",
            ),
        ),
        (
            "待比对事实条数",
            c("scorecard", "runs.baseline.counts.expected_claims"),
            c("live_score", "dataset.scored_claims"),
        ),
        (
            "判定方式",
            note("精确文本匹配 + 词法包含代理", data, "scorecard", "disclaimer"),
            note("AI 语义 judge（qwen-plus）", data, "live_score", "method"),
        ),
        (
            "外部 LLM 调用",
            c("scorecard", "external_calls.llm"),
            c("live_run", "llm_usage.successful_requests"),
        ),
        (
            "外部 Tavily 调用",
            c("scorecard", "external_calls.tavily"),
            c("live_run", "budget.calls_made"),
        ),
        (
            "产物性质",
            note("CI 回归门禁（流程契约不崩）", data, "scorecard", "summary.baseline_gate_passed"),
            note("单次运行观察（不做统计推断）", data, "live_score", "usable_as_resume_metric"),
        ),
    ]


def live_facts(data: dict[str, Any]) -> list[tuple[str, Cell, str]]:
    """§3 真机侧实测事实：每个数字都带出处。"""
    n = lambda key, path: num(data, key, path)  # noqa: E731
    cache_hits = field(data["live_run"], "budget.cache_hits")
    per_search = field(data["live_run"], "credits.credits_per_search")
    return [
        ("报告 company", note(str(field(data["live_run"], "company")), data, "live_run", "company"), "本次唯一一份真实报告"),
        ("报告字符数", n("live_run", "report_checks.chars"), "报告正文长度，不是质量分"),
        ("行内引用标记", n("live_run", "report_checks.inline_citation_markers"), "只数正文，References 的 `[n]` 不计入"),
        ("References 条数", n("live_run", "report_checks.reference_lines"), "编号齐全 ≠ URL 真的支撑结论"),
        ("真实 Tavily 请求", n("live_run", "budget.calls_made"), f"四个栏目各 1 query，其中 {cache_hits} 次命中磁盘缓存"),
        ("缓存命中", n("live_run", "budget.cache_hits"), "缓存命中不扣 credits"),
        ("本轮 credits", n("live_run", "credits.spent_this_run"), f"按官方 advanced={per_search} credits/次推算，非账单"),
        ("累计 credits", n("live_run", "credits.cumulative"), "用户放行上限见下行，本阶段未再消耗"),
        ("用户放行上限", n("live_run", "credits.user_ceiling"), "额度纪律：非必要不调用"),
        ("模型请求", n("live_run", "llm_usage.successful_requests"), "qwen-plus，生产链路"),
        ("模型 tokens", n("live_run", "llm_usage.total_tokens"), "get_openai_callback 捕获"),
        ("单次墙钟 ms", n("live_run", "timing.elapsed_ms"), "含网络往返，非确定性字段，不是 p95"),
        ("词法矛盾", n("live_quality", "checks.contradiction_count"), "同一栏目同时写 2013 / 2014 成立"),
        ("来源域名数", n("live_quality", "checks.source_domain_count"), "含 medium.com 等非一手渠道"),
        ("引用编号完整性", n("live_quality", "checks.citation_integrity_ok"), "只证明 `[n]` 有对应编号，不证明事实正确"),
        ("judge 判定的事实", n("live_score", "dataset.scored_claims"), "其余标准答案没有真实报告可比，如实跳过"),
        ("跳过的事实", n("live_score", "dataset.skipped_claims"), "不凭空生成卷子"),
        ("判定 supported", n("live_score", "summary.supported"), "报告有支持该事实的陈述；不等于来源 URL 真的支持它"),
        ("判定 refuted", n("live_score", "summary.refuted"), "含同一事实自相矛盾的情形"),
        ("判定 not_mentioned", n("live_score", "summary.not_mentioned"), "报告没写到，不等于答错"),
        ("自相矛盾标记", n("live_score", "summary.self_conflict"), "同一事实给了冲突取值，按 prompt 规则判不可靠"),
        ("证据句核对失败", n("live_score", "summary.quote_check_failed"), "引文必须能在报告正文逐字核到"),
        ("judge 模型请求", n("live_score", "usage.successful_requests"), "单独一次，max_retries=0，不与生产链路混算"),
        ("judge tokens", n("live_score", "usage.total_tokens"), "成本单价为 null，不编造"),
        (
            "审计重算差异条数",
            derived(data, "audit", "recheck.delta_vs_original", "列表长度", len),
            "S8.4 复查修复后，既有判定结论无变化",
        ),
        ("审计新增外部调用", n("audit", "isolated_calls.llm_requests"), "事后审计 0 模型 / 0 credits"),
        ("dry-run 最坏预算", n("dryrun", "credit_estimate.worst_case_credits_per_company"), "按官方规则推算的上界，不是实测扣费"),
        ("dry-run query 数", n("dryrun", "budget.query_count"), "完整图最坏情况的 query 清单长度"),
    ]


def ab_rows(data: dict[str, Any]) -> list[tuple[str, str, Cell, Cell, Cell]]:
    """§4 A/B 佐证：只列与「1.000 是契约回归分」直接相关的三组。"""
    names = ["baseline", "no_inline_citations", "self_correction_off"]
    rows = []
    for name in names:
        run = field(data["scorecard"], f"runs.{name}")
        overrides = json.dumps(run.get("overrides") or {}, ensure_ascii=False, sort_keys=True)
        rows.append(
            (
                name,
                overrides if overrides != "{}" else "（无）",
                num(data, "scorecard", f"runs.{name}.metrics.fact_accuracy"),
                num(data, "scorecard", f"runs.{name}.metrics.citation_traceability"),
                num(data, "scorecard", f"runs.{name}.metrics.hallucination_rate"),
            )
        )
    return rows


def known_issue_cells(data: dict[str, Any]) -> list[Cell]:
    """§5 已知问题里出现的可重算数字。"""
    return [
        num(data, "live_quality", "checks.contradiction_count"),
        num(data, "live_quality", "checks.contradictions[0].values"),
        num(data, "live_quality", "checks.source_domain_count"),
        derived(
            data, "live_run", "report", "正文中实体名出现次数",
            lambda text: text.count("Notion VTec Berhad"),
        ),
        num(data, "live_score", "is_human_adjudicated"),
    ]


def table_cells(data: dict[str, Any]) -> list[Cell]:
    """会原样渲染成「值 〔出处〕」的单元格，测试可逐格比对文档。"""
    out: list[Cell] = []
    for row in comparison_rows(data):
        out += [row.fixture, row.live]
    for _, a, b in context_rows(data):
        out += [a, b]
    for _, cell, _ in live_facts(data):
        out.append(cell)
    for _, _, a, b, c in ab_rows(data):
        out += [a, b, c]
    return out


def all_cells(data: dict[str, Any]) -> list[Cell]:
    """文档里所有数值来源：表格单元格 + §5 已知问题的取数单元格。"""
    return table_cells(data) + known_issue_cells(data)


def render(data: dict[str, Any], blocked: int) -> str:
    """纯函数：同样的输入产物必定生成同样的文档（不写时间戳）。"""
    score = data["live_score"]
    run = data["live_run"]
    fixture_metrics = "runs.baseline.metrics"
    fact_accuracy = field(data["scorecard"], f"{fixture_metrics}.fact_accuracy")
    p95 = field(data["scorecard"], f"{fixture_metrics}.p95_latency_ms")
    cost = field(data["scorecard"], f"{fixture_metrics}.cost_per_report")
    elapsed = field(run, "timing.elapsed_ms")
    scored = field(score, "dataset.scored_claims")
    skipped = field(score, "dataset.skipped_claims")
    supported = field(score, "summary.supported")
    total_claims = field(score, "dataset.total_claims_in_golden")
    cumulative = field(run, "credits.cumulative")
    ceiling = field(run, "credits.user_ceiling")
    entity_hits = known_issue_cells(data)[-2].value
    contradiction_values = known_issue_cells(data)[1].value
    domain_count = field(data["live_quality"], "checks.source_domain_count")
    domains = field(data["live_quality"], "checks.source_domains")

    def cell(c: Cell) -> str:
        return f"{c.text} 〔{c.ref}〕" if c.ref else c.text

    L: list[str] = []
    L += [
        "# S8.5 假数据契约回归 vs 真机表现（对比表）",
        "",
        "> **一句话**：fixture 上的满分是「流程契约没崩」，真机第一份报告就暴露了"
        "自相矛盾、来源污染、实体混淆三类硬伤。两侧测的不是同一个东西，"
        "**不能相减、不能说「掉了多少」，更不能用 fixture 的数字冒充真实效果**。",
        ">",
        f"> 本文由 `evals/build_live_report.py` 从 {len(FILES)} 份既有产物生成，"
        f"生成时禁网守卫拦截到 **{blocked}** 次外部连接，**0 次模型请求 / 0 Tavily credits**。"
        "每个数字后标「文件 → 字段」，可用 `tests/test_s8_live_report.py` 逐项重算。"
        "**请勿手改本文**，要改请改生成脚本。",
        "",
        "## 0. 怎么复现",
        "",
        "```bash",
        "uv run python -m evals.build_live_report       # 只读 6 份产物，重新生成本文",
        "uv run pytest -q tests/test_s8_live_report.py  # 逐个数字按出处重算",
        "```",
        "",
        "生成脚本复用 `evals/run_eval.py` 的禁网守卫：非回环连接立即抛错，"
        "因此这条命令**物理上不可能**消耗 Tavily / 模型额度；"
        f"本次实测拦截计数 {blocked}。",
        "",
        "## 1. 先讲清口径：两侧根本不是一回事",
        "",
        "| 维度 | fixture 契约回归（S7） | 真机实测（S8） |",
        "|---|---|---|",
    ]
    for label, a, b in context_rows(data):
        L.append(f"| {label} | {cell(a)} | {cell(b)} |")
    L += [
        "",
        f"fixture 侧 `provenance = {field(data['scorecard'], 'provenance')}`、"
        f"`mode = {field(data['scorecard'], 'mode')}`，文件自带免责声明原话：",
        "",
        f"> {field(data['scorecard'], 'disclaimer')}",
        "",
        "真机侧只有一份报告、一次运行，**没有统计意义上的分布**；"
        "`p95` / 成本 / 准确率这类需要多样本与人工判定的指标，一律按「未测」处理。",
        "",
        "## 2. 核心对比表（逐项说清「真机到底测没测」）",
        "",
        "| 指标 | fixture 侧 | 真机侧 | 说明 |",
        "|---|---|---|---|",
    ]
    for row in comparison_rows(data):
        L.append(f"| {row.metric} | {cell(row.fixture)} | {cell(row.live)} | {row.note} |")
    L += [
        "",
        f"**表里最容易被误用的一格**：`p95_latency_ms = {p95}` 与 "
        f"`cost_per_report = {cost}` 都在 fixture 合成语料 + "
        f"{field(data['scorecard'], 'external_calls.llm')} 次 LLM / "
        f"{field(data['scorecard'], 'external_calls.tavily')} 次 Tavily 调用下产生。"
        f"真机那份报告的单次墙钟是 {elapsed} ms（`timing.note` 明写「不代表 p95」），"
        "`llm_usage.total_cost_usd` 是 `null`。**这几个数不是真实 p95、不是真实成本；"
        "准确说法是：fixture 侧有值、真机侧全部未测。**",
        "",
        "## 3. 真机侧实测事实（可逐个复核）",
        "",
        "| 项 | 值 | 出处 / 说明 |",
        "|---|---|---|",
    ]
    for label, c, note_text in live_facts(data):
        L.append(f"| {label} | {cell(c)} | {note_text} |")
    L += [
        "",
        f"额度纪律：累计 **{cumulative} / {ceiling} credits**（S8.2 探针 + S8.3 端到端），"
        "S8.4 的 judge 与 S8.5 的本文都是 0 credits。",
        "",
        f"## 4. 为什么 `fact_accuracy = {fact_accuracy}` 只是「流程契约分」：A/B 组就是证据",
        "",
        "| 组 | 关掉的开关 | `fact_accuracy` | `citation_traceability` | `hallucination_rate` |",
        "|---|---|---|---|---|",
    ]
    for name, overrides, a, b, c in ab_rows(data):
        L.append(f"| `{name}` | `{overrides}` | {cell(a)} | {cell(b)} | {cell(c)} |")
    L += [
        "",
        "关掉行内引用，`citation_traceability` 从 "
        f"{field(data['scorecard'], 'runs.baseline.metrics.citation_traceability')} 掉到 "
        f"{field(data['scorecard'], 'runs.no_inline_citations.metrics.citation_traceability')}、"
        f"`hallucination_rate` 升到 "
        f"{field(data['scorecard'], 'runs.no_inline_citations.metrics.hallucination_rate')}，"
        "而 `fact_accuracy` 纹丝不动；关掉自纠正，`fact_accuracy` 变成 "
        f"{field(data['scorecard'], 'runs.self_correction_off.metrics.fact_accuracy')}。"
        "**分数随开关变化，说明它测的是「图有没有按预期执行」，不是「报告写得好不好」。**"
        "（`p95_latency_ms` 是非确定性字段，不参与 A/B 判定，故本表不列。）",
        "",
        "## 5. 已知问题：真机报告的三类硬伤（项目发现，未修）",
        "",
        "| 问题 | 证据 | 可能原因（待验证） |",
        "|---|---|---|",
        f"| 自相矛盾 | 同一 Company 栏目同时写 "
        f"{' / '.join(str(v) for v in contradiction_values)} 年成立"
        f" 〔{ref_of('live_quality', 'checks.contradictions[0].values')}〕；"
        f"`checks.contradiction_count` = {field(data['live_quality'], 'checks.contradiction_count')}"
        f" 〔{ref_of('live_quality', 'checks.contradiction_count')}〕 | "
        "多来源未做冲突消解，结构化抽取把两句都当事实收下 |",
        f"| 来源污染 / 事实错 | 总部写成伦敦某门牌；来源域名共 {domain_count} 个"
        f" 〔{ref_of('live_quality', 'checks.source_domain_count')}〕，"
        f"含 `medium.com`（{'有' if 'medium.com' in domains else '无'}记录）"
        f" 〔{ref_of('live_quality', 'checks.source_domains')}〕 | "
        "同名实体 / 低质来源混入，检索 query 未消歧 |",
        f"| **实体混淆** | Financial 栏目正文里 `Notion VTec Berhad` 出现 **{entity_hits}** 次"
        f" 〔{ref_of('live_run', 'report')}（词频）〕，"
        "是马来西亚上市公司 0083.KL 的股价指标，与 Notion Labs 不是同一家 | "
        "检索命中同名股票代码，未做实体一致性检查 |",
        f"| judge 措辞瑕疵 | `is_human_adjudicated = "
        f"{show(field(score, 'is_human_adjudicated'))}` 〔{ref_of('live_score', 'is_human_adjudicated')}〕；"
        "`notion:company:2` 的 reason 漏看了正文里出现过一次的 CEO 提及 | "
        "AI judge 未经人工抽检一致率校准，故产物标 `usable_as_resume_metric=false` |",
        "",
        "这三类是**真实运行才暴露**的问题，fixture 满分完全测不出来。"
        "能把问题定位到具体栏目、具体来源域名、具体实体名，"
        "正是「评测链路可用」的证据——比一个漂亮的分数更经得住面试追问。"
        "S8.5 只做记录与对比，**不修、也不复测**（复测要另花 Tavily 额度，需单独规划）。",
        "",
        "## 6. 不能写成什么（红线清单）",
        "",
        f"- ❌ `fact_accuracy = {fact_accuracy}` 写成"
        "「系统效果好 / 准确率高」——它是合成语料契约回归分，§4 已证随开关变化。",
        f"- ❌ `supported = {supported}`（共 {scored} 条）写成「准确率 0%」——"
        f"其中 {field(score, 'summary.not_mentioned')} 条是「报告没写到」，不是「写反了」；"
        "judge 是 AI 判定、非人工评分。",
        f"- ❌ 把 `p95_latency_ms = {p95}` 或单次墙钟 {elapsed} ms 写成「真实 p95」。",
        f"- ❌ 把 `cost_per_report = {cost}` 写成「零成本」——那来自 "
        f"{field(data['scorecard'], 'external_calls.tavily')} 次外部调用；"
        "`total_cost_usd = null` 就保持 null，不套用 qwen-plus 之外的价目表。",
        f"- ❌ 把 {total_claims} 条 golden 写成「都测了」——当前只有 {scored} 条有真实报告可比，"
        f"另 {skipped} 条如实跳过。",
        "- ❌ 编造真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价；"
        "golden 引用层（最终 URL 是否支撑事实）未核验，引用类指标尤其不能出数。",
        "- ❌ 写「上线 / 甲方 / 用户量 / 效果提升 X%」——本项目是个人工程复现，没有这些事实。",
        "",
        "## 7. 能写进简历的（工程事实，不是效果数字）",
        "",
        f"- 基于 LangGraph 的公司调研 Agent：并行子图检索、栏目级自纠正、结构化输出、"
        "HITL 中断/恢复、checkpoint 持久化；fixture/live 双模式 + 禁网守卫 + 调用预算三重放行。",
        f"- 建立 {total_claims} 条人工核验 golden 与 AI 语义 judge 链路，"
        "把真机报告的问题定位到栏目与来源级别（§5）。",
        f"- 累计 {cumulative} / {ceiling} credits 的额度纪律下完成 1 份端到端真实报告；"
        "S8.4 复查用只读探针坐实并修复评测链路缺陷（见 `docs/LIVE_SCORE.md` §7），"
        "事后审计重算无差异。",
        "- 评测台 + CI 回归门禁：A/B 组能量化各开关对契约指标的影响。",
        "",
        "本段复用的数字（golden 条数、累计 / 上限 credits）与 §3 同源，"
        "由同一批字段插值生成，出处见 §3 对应行与 §8 产物索引；"
        "这里不引入任何新测量值。",
        "",
        "## 8. 输入产物索引",
        "",
        "| 文件 | 在本文里的角色 |",
        "|---|---|",
    ]
    roles = {
        "scorecard": "fixture 契约回归分、A/B 组、0 外部调用声明",
        "live_run": f"{run['company']} 端到端真实报告、预算/额度/耗时",
        "live_quality": "0 调用词法质量检查（矛盾、来源域名、引用编号）",
        "live_score": "5 条 AI 语义判定与指标边界",
        "audit": "S8.4 复查的 0 差异事后审计",
        "dryrun": "0 调用预算推算（最坏 query 数 / credits 上界）",
    }
    for key, rel in FILES.items():
        L.append(f"| `{rel}` | {roles[key]} |")
    L += [
        "",
        "## 9. 状态",
        "",
        f"- 本文生成：**{blocked}** 次外部连接、**0** 次模型请求、**0** Tavily credits；"
        f"累计 Tavily 仍 **{cumulative} / {ceiling}**。",
        f"- 真实准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价：**{NOT_MEASURED}**；"
        f"上面的累计额度取自 `{FILES['live_run']}` → `credits.cumulative` / `user_ceiling`。",
        "- 之后：S8.6 `docs/RESUME_EVIDENCE.md` 数字出处表 → S9 简历描述 + 面试追问清单。",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    # 延迟导入：测试只调 render()，不必把 S7 评测台的依赖带进测试进程。
    from evals.run_eval import eval_offline_guard

    with eval_offline_guard("S8.5 对比表生成") as attempts:
        data = load_inputs()
        text = render(data, blocked=len(attempts))
    assert not attempts, f"生成过程中出现外部连接，拒绝写文档：{attempts!r}"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"[S8.5] 0 调用生成 -> {OUTPUT.relative_to(ROOT).as_posix()} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
