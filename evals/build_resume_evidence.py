"""S8.6：生成「简历数字出处表」docs/RESUME_EVIDENCE.md。

    uv run python -m evals.build_resume_evidence                  # 重新生成本文（0 调用）
    uv run python -m evals.build_resume_evidence --verify         # 逐条执行复现命令并比对（0 调用）
    uv run python -m evals.build_resume_evidence --record-commits # 刷新 commit 台账（0 调用）

设计红线（对应 ACTION_PLAN 任务表 S8.6 行与 12.3 硬约束）：

1. **只读取既有产物**，不跑模型、不跑 Tavily、不重算评测；生成过程装
   `eval_offline_guard`，任何外部连接都会抛错而不是消耗额度。
2. **每条数字四要素齐全**：值 / 出处文件 + 字段 / 该文件最后一次修改的 commit /
   一条能当场执行的复现命令。复现命令由 (文件, 字段路径) **自动生成**，
   不手写，因此出处与命令不可能脱节。
3. **模板不写死任何数字或 commit**：数值从产物插值，commit 从台账
   `evals/resume_evidence_commits.json` 读（见 `commit_note()`）。
4. **如实区分可写与禁写**：fixture 合成语料的分、单次墙钟、AI judge 判定、
   null 成本一律不得当真实效果；归因红线（Apache-2.0 二次开发）单列。
5. 产物是「出处表」，不是新指标：真实准确率 / 幻觉率 / 引用可追溯率 /
   p95 / 成本单价一律写「未测」。
6. **commit 列必须冻结**（S8.6 复查修复）：早期版本每次渲染都现场跑
   `git log -1`，导致「提交前生成、提交后失效」——任何一次新提交改到被引用
   的文件，文档里的 hash 就与 `render()` 不一致，测试必红。改为首次渲染时
   把「录入时该文件的最后修改提交」写进台账并提交，之后只读台账；
   `tests/test_s8_resume_evidence.py` 用 `git show <commit>:<file>` 校验
   该值在那个 commit 里确实存在，比「最后一次提交」更接近简历要的语义。
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "RESUME_EVIDENCE.md"
COMMITS_PATH = ROOT / "evals" / "resume_evidence_commits.json"

# 除产物外，文档里还点名了这些文件（禁写清单、归因、对比表）
DOC_REFS: tuple[str, ...] = (
    "docs/UPSTREAM.md",
    "docs/ACTION_PLAN.md",
    "docs/LIVE_REPORT.md",
    "docs/LIVE_BATCH.md",
    "LICENSE",
)

FILES: dict[str, str] = {
    "scorecard": "evals/scorecard.json",
    "live_run": "evals/live_run.json",
    "live_quality": "evals/live_quality.json",
    "live_score": "evals/live_score.json",
    "audit": "evals/live_score_audit.json",
    "dryrun": "evals/live_dryrun.json",
    "live_probe": "evals/live_probe.json",
    "llm_probe": "evals/llm_probe.json",
    "golden_live": "evals/golden_live.jsonl",
    "review_filled": "evals/golden_live_review_filled.jsonl",
    # S10-B 批量真实调研
    "live_batch": "evals/live_batch.json",
    "live_score_batch": "evals/live_score_batch.json",
    "ledger": "evals/credits_ledger.json",
}

NOT_MEASURED = "未测"

# 分组顺序 = 文档顺序。新增一组必须登记在这里：§2 的分表与 §3 的措辞都由它驱动，
# 漏登记会让 `Fact.group` 指向表外的字母，测试当场红（S10-B 就漏过一次）。
GROUPS: tuple[tuple[str, str, str], ...] = (
    ("A", "真机一次端到端报告", "真机实测"),
    ("B", "评测工程与数据可信度", "评测工程"),
    ("C", "额度纪律", "额度纪律"),
    ("D", "批量真实调研（S10-B）", "批量真实调研"),
)
GROUP_IDS = tuple(gid for gid, _, _ in GROUPS)


def upstream_commit() -> str:
    """从 docs/UPSTREAM.md 现场读落地 commit，不在模板里硬编码 hash。"""
    import re

    text = (ROOT / "docs" / "UPSTREAM.md").read_text(encoding="utf-8")
    m = re.search(r"落地 commit\s*\|\s*`([0-9a-f]{7,40})`", text)
    if not m:
        raise RuntimeError("docs/UPSTREAM.md 里找不到上游落地 commit")
    return m.group(1)[:7]


def load_inputs() -> dict[str, Any]:
    """只读加载产物；缺文件直接报错，不静默 fallback。"""
    out: dict[str, Any] = {}
    for key, rel in FILES.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        out[key] = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if rel.endswith(".jsonl")
            else json.loads(text)
        )
    return out


def field(doc: Any, dotted: str) -> Any:
    """按点路径取值，支持 `a.b[0].c`。与文档里打印的出处路径共用一套解析。"""
    cur = doc
    for part in dotted.replace("[", ".").replace("]", "").split("."):
        if part.isdigit() and isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(f"字段不存在：{dotted}（停在 {part!r}）")
    return cur


def expr_from_path(path: str) -> str:
    """把 `a.b[0].c` 变成 `d["a"]["b"][0]["c"]`，供复现命令使用。"""
    out = "d"
    for part in path.replace("[", ".").replace("]", "").split("."):
        out += f"[{part}]" if part.isdigit() else f'["{part}"]'
    return out


def _loader(rel: str, var: str) -> str:
    if rel.endswith(".jsonl"):
        return f'{var}=[json.loads(l) for l in open("{rel}", encoding="utf-8") if l.strip()]'
    return f'{var}=json.load(open("{rel}", encoding="utf-8"))'


@dataclass(frozen=True)
class Fact:
    fid: str
    label: str
    key: str
    path: str
    resume: str  # 简历可用措辞模板，{v} 为数值占位
    note: str
    group: str
    expr: str | None = None  # 默认由 path 生成
    derive: Callable[[Any], Any] | None = None  # 默认 field(doc, path)
    sources: tuple[str, ...] | None = None  # 跨文件求值时按顺序加载为 d0/d1/...
    derive_all: Callable[[dict[str, Any]], Any] | None = None

    def source_keys(self) -> tuple[str, ...]:
        return self.sources or (self.key,)

    def value(self, data: dict[str, Any]) -> Any:
        if self.derive_all:
            return self.derive_all(data)
        doc = data[self.key]
        return self.derive(doc) if self.derive else field(doc, self.path)

    def expression(self) -> str:
        return self.expr or expr_from_path(self.path)

    def code(self) -> str:
        """一条独立、可直接执行的 python -c 代码：只读原始产物，不依赖本脚本。

        单文件用变量 `d`；跨文件（`sources`）按顺序用 `d0/d1/...`。
        """
        keys = self.source_keys()
        loads = [_loader(FILES[k], "d" if len(keys) == 1 else f"d{i}") for i, k in enumerate(keys)]
        return (
            "import json; " + "; ".join(loads)
            + f"; print(json.dumps({self.expression()}, ensure_ascii=False))"
        )

    def command(self) -> str:
        # 代码内部只用双引号，外层用单引号包裹，bash / PowerShell 均可直接执行。
        return f"uv run python -c '{self.code()}'"

    def source_ref(self) -> str:
        files = " + ".join(f"`{FILES[k]}`" for k in self.source_keys())
        return f"{files} → `{self.path}`"

    def commits(self) -> list[str]:
        return [file_commit(FILES[k]) for k in self.source_keys()]


def show(value: Any) -> str:
    """与复现命令的 stdout 完全同构（json.dumps），保证逐字可比。"""
    return json.dumps(value, ensure_ascii=False)


def facts() -> list[Fact]:
    """S8.6 收录的全部数字。按「简历里真会用得上」筛选，不堆砌。"""
    return [
        # --- A. 真机一次端到端报告 ---
        Fact("F01", "累计 Tavily credits", "live_run", "credits.cumulative",
             "在累计 {v} credits 的预算内完成端到端真实调研（按官方计费规则推算，非账单）",
             "含 S8.2 单次探针；按官方 advanced=2 credits/次推算，非扣费账单", "A"),
        Fact("F02", "用户设定的 credits 硬上限", "live_run", "credits.user_ceiling",
             "为用户额度设 {v} credits 硬上限，全程未突破",
             "上限是用户放行值，不是 Tavily 免费额度总量", "A"),
        Fact("F03", "本轮 credits", "live_run", "credits.spent_this_run",
             "单次报告消耗 {v} credits",
             "按 `budget.calls_made` × `credits.credits_per_search` 推算；缓存命中不扣", "A"),
        Fact("F04", "真实检索次数", "live_run", "budget.calls_made",
             "单次调研发起 {v} 次真实联网检索",
             "CallBudget 记录的生产路径调用数", "A"),
        Fact("F05", "缓存命中次数", "live_run", "budget.cache_hits",
             "引入 sha256 检索缓存，单次运行命中 {v} 次",
             "命中不产生额度消耗", "A"),
        Fact("F06", "模型请求次数", "live_run", "llm_usage.successful_requests",
             "单次报告完成 {v} 次大模型请求",
             "get_openai_callback 捕获；不含 S8.4 judge 的请求", "A"),
        Fact("F07", "模型 token 用量", "live_run", "llm_usage.total_tokens",
             "单次报告消耗 {v} tokens",
             "真实计数；但单价未知，不换算成本", "A"),
        Fact("F08", "报告字符数", "live_run", "report_checks.chars",
             "产出 {v} 字符的四栏目带引用简报",
             "词法统计，不代表内容质量", "A"),
        Fact("F09", "参考文献条目", "live_run", "report_checks.reference_lines",
             "简报附 {v} 条参考来源",
             "仅为条目数，引用可追溯率未测", "A"),
        Fact("F10", "正文行内引用标记", "live_run", "report_checks.inline_citation_markers",
             "正文含 {v} 处行内引用标记",
             "只数 ## References 之前的正文；不代表引用正确", "A"),
        Fact("F11", "单次墙钟耗时(ms)", "live_run", "timing.elapsed_ms",
             "单次端到端墙钟 {v} ms（**不是 p95**）",
             "含网络往返，非确定性字段；不得写成 p95 / 平均延迟", "A"),
        Fact("F12", "dry-run 预算 query 数", "dryrun", "budget.query_count",
             "0 调用预演出完整调研最多会发 {v} 条 query",
             "预算推算，非真实请求；真实检索次数见 F04", "A"),
        Fact("F26", "报告栏目数", "live_run", "len(config.sections)",
             "输出 {v} 个固定栏目（Company / Industry / Financial / News）",
             "栏目结构固定；每栏内容质量另见 F17 / F18 的批改口径", "A",
             expr='len(d["config"]["sections"])',
             derive=lambda d: len(d["config"]["sections"])),
        # --- B. 评测工程 / 数据可信度 ---
        Fact("F13", "人工核验标准答案条数", "golden_live",
             'len([r for r in lines if r["kind"] == "claim"])',
             "构建 {v} 条人工核验的事实标准答案",
             "事实层经用户逐条复核；引用层未核验", "B",
             expr='len([r for r in d if r["kind"] == "claim"])',
             derive=lambda d: len([r for r in d if r["kind"] == "claim"])),
        Fact("F14", "覆盖公司数", "golden_live",
             'len({r["case"] for r in lines if r["kind"] == "claim"})',
             "标准答案覆盖 {v} 家公司",
             "其中仅 `live_run.company` 一家有真实报告；可对答案的条数见 F17", "B",
             expr='len({r["case"] for r in d if r["kind"] == "claim"})',
             derive=lambda d: len({r["case"] for r in d if r["kind"] == "claim"})),
        Fact("F15", "用户二次修订条数", "golden_live", "0.claims_revised_by_user",
             "二次复核修订 {v} 条最终标准答案",
             "正式 golden 同时保留草稿版与最终版，可追溯改动", "B"),
        Fact("F16", "替换掉的不可达原始 URL", "golden_live", "0.original_unreachable_source_urls",
             "复核发现并替换 {v} 条打不开的原始出处",
             "新 URL 未在本项目内重新抓取，引用层仍不可算指标", "B"),
        Fact("F17", "真机可比对条数", "live_score", "dataset.scored_claims",
             "语义批改实际比对 {v} 条事实",
             "样本仅为 `live_run.company` 一家一份报告，不代表整体准确率", "B"),
        Fact("F18", "因无报告而跳过的条数", "live_score", "dataset.skipped_claims",
             "{v} 条标准答案如实跳过（无对应真实报告，不编造）",
             "体现评测口径纪律，不是漏测", "B"),
        Fact("F19", "语义 judge 请求次数", "live_score", "usage.successful_requests",
             "AI 语义批改链路由 {v} 次模型请求完成",
             "如实标 AI judge 非人工裁定，不作为简历指标", "B"),
        Fact("F20", "语义 judge token 用量", "live_score", "usage.total_tokens",
             "语义批改消耗 {v} tokens",
             "单价未知，不换算成本", "B"),
        Fact("F21", "审计重算差异条数", "audit",
             "len(recheck.delta_vs_original)",
             "评测链路修复后事后审计重算差异 {v} 条",
             "0 差异代表修复未改变既有判定，不代表判定正确", "B",
             expr='len(d["recheck"]["delta_vs_original"])',
             derive=lambda d: len(d["recheck"]["delta_vs_original"])),
        Fact("F22", "fixture 评测组总数", "scorecard",
             "len(summary.groups_run)",
             "评测台内置 {v} 个评测组（含 baseline 与开关 A/B 组）",
             "fixture 合成语料，测流程契约不测真实效果；除 baseline 外才是 A/B 对照", "B",
             expr='len(d["summary"]["groups_run"])',
             derive=lambda d: len(d["summary"]["groups_run"])),
        Fact("F27", "评测指标项数", "scorecard", "len(runs.baseline.metrics)",
             "评测台覆盖 {v} 项指标",
             "fixture 合成语料；指标定义见 `evals/metrics.py`，不代表真机效果", "B",
             expr='len(d["runs"]["baseline"]["metrics"])',
             derive=lambda d: len(d["runs"]["baseline"]["metrics"])),
        Fact("F28", "fixture 用例数", "scorecard", "runs.baseline.counts.cases",
             "fixture 回归覆盖 {v} 个用例场景",
             "合成语料，只测流程契约；真实样本见 F13 / F14", "B"),
        Fact("F29", "fixture 标准答案条数", "scorecard", "runs.baseline.counts.expected_claims",
             "fixture 集含 {v} 条标准 claim",
             "合成语料；人工核验的真实 golden 见 F13", "B"),
        # --- C. 额度纪律 ---
        Fact("F23", "fixture 回归外部 Tavily 调用", "scorecard", "external_calls.tavily",
             "fixture 契约回归全程 {v} 次外部检索",
             "禁网守卫保证回归不会误耗额度", "C"),
        Fact("F24", "语义 judge 的 Tavily 调用", "live_score",
             "isolation.tavily_client_search_calls",
             "语义批改环节 {v} 次检索",
             "judge 只读本地报告；额度消耗见 `isolation.tavily_credits_used`", "C"),
        Fact("F25", "最小真实探针 credits", "live_probe", "credits.estimated_credits_used",
             "用 {v} credits 的最小探针坐实真实检索返回结构",
             "按官方规则推算；真实累计见 F01", "C"),
        Fact("F31", "单次 advanced 检索计费", "live_run", "credits.credits_per_search",
             "按官方计费规则，每次 advanced 检索计 {v} credits",
             "官方规则推算，不是账单；缓存命中不扣", "C"),
        Fact("F30", "S8 累计真实模型请求", "live_run",
             "llm_probe + live_run + live_score 三处求和",
             "S8 阶段累计 {v} 次真实模型请求（兼容性探针 + 端到端报告 + 语义批改）",
             "分项见 F06 / F19 与 `evals/llm_probe.json`；成本仍 null", "C",
             sources=("llm_probe", "live_run", "live_score"),
             expr='d0["usage"]["successful_requests"]+d1["llm_usage"]["successful_requests"]'
                  '+d2["usage"]["successful_requests"]',
             derive_all=lambda data: (
                 data["llm_probe"]["usage"]["successful_requests"]
                 + data["live_run"]["llm_usage"]["successful_requests"]
                 + data["live_score"]["usage"]["successful_requests"]
             )),
        # --- D. 批量真实调研（S10-B）---
        Fact("F32", "批量真实调研公司数", "live_batch", "len(companies)",
             "一次批量真实调研覆盖 {v} 家公司",
             "Notion 复用 S8.3 磁盘缓存（0 credits），其余为新检索", "D",
             expr='len(d["companies"])',
             derive=lambda d: len(d["companies"])),
        Fact("F33", "可批改标准答案条数", "live_score_batch", "aggregate.scored_claims",
             "把 {v} 条人工核验标准答案全部对上真实报告",
             "全部经用户逐条复核；引用层仍未核验，不是准确率的分母", "D"),
        Fact("F34", "判为支持的条数", "live_score_batch", "aggregate.supported",
             "其中 {v} 条被报告完整支持",
             "supported 只表示报告里有这句话，不代表来源 URL 真的支持它", "D"),
        Fact("F35", "判为反证的条数", "live_score_batch", "aggregate.refuted",
             "{v} 条被判为与标准答案矛盾",
             "含 judge 口径偏严的情形（见 `docs/LIVE_BATCH.md` §5），不等于系统答错", "D"),
        Fact("F36", "判为未提及的条数", "live_score_batch", "aggregate.not_mentioned",
             "{v} 条报告未写到",
             "未提及不等于答错；把它算错或排除会得到两个都不该叫准确率的数", "D"),
        Fact("F37", "引文校验失败条数", "live_score_batch", "aggregate.quote_check_failed",
             "批改的引文逐字校验失败 {v} 条",
             "0 说明每条判定都有可核到的原文证据，不是模型凭印象编的", "D"),
        Fact("F38", "Tavily credits 累计", "ledger", "total_credits",
             "全部真实检索累计 {v} credits（含一次失败重跑的损失）",
             "台账在 `evals/credits_ledger.json`；失败的运行也照记", "D"),
        Fact("F39", "实体消歧拒绝篇次", "live_batch", "summary.entity_guard_rejections",
             "实体消歧在真实数据上触发 {v} 次拒绝",
             "是「篇次」不是「篇数」：2 篇不同文档各被首轮与补搜两次判定", "D"),
    ]


@lru_cache(maxsize=None)
def file_commit(rel: str) -> str:
    """该出处文件**录入时**的最后一次修改 commit，从台账读，不现场问 git。

    台账由 `--record-commits` 写入并入库；渲染只读它，因此新提交即使改到这些
    文件，文档里的 hash 也不会漂移（早期版本正是在这里每提交一次就必红）。
    """
    commits = recorded_commits()
    if rel not in commits:
        raise RuntimeError(
            f"{rel} 未登记 commit；先运行 "
            "`uv run python -m evals.build_resume_evidence --record-commits`"
        )
    return commits[rel]


@lru_cache(maxsize=None)
def recorded_commits() -> dict[str, str]:
    if not COMMITS_PATH.exists():
        raise RuntimeError(
            f"commit 台账不存在：{COMMITS_PATH.relative_to(ROOT).as_posix()}；"
            "先运行 `uv run python -m evals.build_resume_evidence --record-commits`"
        )
    raw = json.loads(COMMITS_PATH.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in raw.items()}


def live_commit(rel: str) -> str:
    """现场问 git：该文件当前（HEAD/工作区）的最后一次修改提交。"""
    r = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", rel],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    commit = r.stdout.strip()
    if not commit:
        raise RuntimeError(f"文件未纳入 git，无法给出 commit：{rel}")
    return commit


def referenced_files() -> list[str]:
    """台账必须覆盖的路径：全部产物 + 文档里点名的其他文件。"""
    return sorted(set(FILES.values()) | set(DOC_REFS))


def record_commits() -> dict[str, str]:
    """把当前 HEAD 下各文件的最后修改提交写进台账（唯一会写台账的入口）。"""
    return {rel: live_commit(rel) for rel in referenced_files()}


def run_verification(data: dict[str, Any]) -> list[dict[str, Any]]:
    """逐条**实际执行**复现命令，比对 stdout 与产物取值。不做任何网络调用。

    单条失败（产物字段被删、命令报错、值不符）只让该条 FAIL，
    不中断其余条目 —— 否则「哪条断了」会被一个 traceback 掩盖。
    """
    rows: list[dict[str, Any]] = []
    for f in facts():
        row: dict[str, Any] = {
            "fid": f.fid, "label": f.label, "command": f.command(),
            "expected": None, "actual": None, "returncode": None, "stderr": "", "ok": False,
        }
        try:
            row["expected"] = show(f.value(data))
            r = subprocess.run(
                [sys.executable, "-c", f.code()],
                cwd=ROOT, capture_output=True, text=True,
            )
            row["returncode"] = r.returncode
            row["stderr"] = r.stderr.strip()[:300]
            row["actual"] = r.stdout.strip()
            row["ok"] = r.returncode == 0 and row["actual"] == row["expected"]
        except Exception as exc:  # 字段缺失 / 编码错误 / 子进程启动失败
            row["actual"] = f"<{type(exc).__name__}: {exc}>"
        rows.append(row)
    return rows


def fact_table(data: dict[str, Any], group: str) -> list[str]:
    rows = [f for f in facts() if f.group == group]
    out = [
        "| 编号 | 数字 | 值 | 出处（文件 → 字段） | commit | 复现命令 |",
        "|---|---|---:|---|---|---|",
    ]
    for f in rows:
        commits = " / ".join(f"`{h}`" for h in f.commits())
        out.append(
            f"| `{f.fid}` | {f.label} | `{show(f.value(data))}` | "
            f"{f.source_ref()} | {commits} | `{f.command()}` |"
        )
    return out


def banned_rows() -> list[tuple[str, str, str, str]]:
    """禁止写法 / 事实 / 出处 / 说明。出处同样带文件与 commit。"""
    def ref(key: str, path: str) -> str:
        rel = FILES[key]
        return f"`{rel}` → `{path}` 〔`{file_commit(rel)}`〕"

    upstream = f"`docs/UPSTREAM.md` → 落地 commit 〔`{file_commit('docs/UPSTREAM.md')}`〕；根目录 `LICENSE` 〔`{file_commit('LICENSE')}`〕"
    plan = f"`docs/ACTION_PLAN.md` → 12.3 硬约束 〔`{file_commit('docs/ACTION_PLAN.md')}`〕"
    return [
        ("❌「准确率 100% / 效果好」",
         "fixture `fact_accuracy` 是合成语料契约回归分",
         ref("scorecard", "runs.baseline.metrics.fact_accuracy"),
         "关开关就会变，测的是流程不是效果"),
        ("❌「p95 延迟 X ms」",
         "fixture `p95_latency_ms` 是本机合成语料耗时",
         ref("scorecard", "runs.baseline.metrics.p95_latency_ms"),
         "0 外部调用；真机 p95 未测"),
        ("❌「零成本 / 每份 X 元」",
         "fixture `cost_per_report` 与真机 `total_cost_usd` 均不可当成本",
         ref("scorecard", "runs.baseline.metrics.cost_per_report"),
         "真机 `" + FILES["live_run"] + "` → `llm_usage.total_cost_usd` 为 null 〔`"
         + file_commit(FILES["live_run"]) + "`〕；qwen-plus 单价不在价目表内"),
        ("❌「幻觉率 0%」",
         "fixture `hallucination_rate` 只反映词法代理",
         ref("scorecard", "runs.baseline.metrics.hallucination_rate"),
         "引用层未核验，真机幻觉率未测"),
        ("❌「准确率 0%（因为 supported=0）」",
         "AI judge 的 supported 计数是极少量样本的判定分布",
         ref("live_score", "summary.supported"),
         "`usable_as_resume_metric=false`、`is_human_adjudicated=false`"),
        ("❌ 把 judge 结果写成人工评测指标",
         "judge 是 AI 判定，未经人工抽检一致率校准",
         ref("live_score", "is_human_adjudicated"),
         "样本见 F17 / F18，另有措辞瑕疵记录"),
        ("❌「独立开发 / 从零自研」",
         "本项目基于上游仓库二次开发（Apache-2.0）",
         upstream,
         "必须保留 LICENSE 与上游 commit 归因"),
        ("❌「上线 / 甲方 / 用户量 / 效果提升 X%」",
         "本项目是本地个人工程复现，无这些事实",
         plan,
         "简历只写「本地实测」"),
        ("❌「引用可追溯率 X%」",
         "最终 URL 多数未在本项目内重新抓取核验",
         ref("golden_live", "0.citation_layer_usable_as_metric"),
         "引用层指标明确不可用"),
    ]


def render(data: dict[str, Any], blocked: int) -> str:
    f = facts()
    by_id = {x.fid: x for x in f}
    v = lambda fid: show(by_id[fid].value(data))  # noqa: E731
    L: list[str] = []
    add = L.append

    add("# 简历数字出处表（S8.6）")
    add("")
    add("> **一句话**：这份表只收录「能当场复现」的数字，每条都给出值、出处文件 + 字段、"
        "该文件最后修改的 commit、以及一条可直接执行的复现命令。"
        "复现不了的一律不写。")
    add("")
    add("**归因红线**：本项目基于 `guy-hartstein/company-research-agent`（Apache-2.0）二次开发，"
        f"`LICENSE` 与上游 commit `{upstream_commit()}` 均保留；简历不得写「独立开发」，"
        "只写「本地实测」，不写甲方 / 上线 / 用户量。")
    add("")
    add("```bash")
    add("uv run python -m evals.build_resume_evidence --verify   # 逐条执行复现命令并比对")
    add("uv run pytest -q tests/test_s8_resume_evidence.py      # 护栏：命令、commit、禁写清单")
    add("```")
    add("")
    add(f"生成过程装 `eval_offline_guard`，本次实测拦截外部连接 **{blocked}** 次；"
        "本阶段 **0** 次模型请求、**0** Tavily credits。")
    add("")
    add("## 1. 使用规则")
    add("")
    add("- 只有在 §2 表里的数字才允许进入简历措辞，且必须带上其口径限定"
        "（例如 F11 只能写「单次墙钟」，不能写 p95）。")
    add("- `commit` 列是**录入时**该文件的最后一次修改提交，冻结在 "
        "`evals/resume_evidence_commits.json`，不随之后的新提交漂移；"
        "刷新台账用 `--record-commits`。它不是本文的提交，也不代表该数字首次出现的版本。")
    add("- 护栏会用 `git show <commit>:<文件>` 复核：**该数值在那个 commit 里确实存在**，"
        "比「最后一次修改」更接近简历要的语义；文档文件则只校验存在性。")
    add("- 复现命令从 (文件, 字段路径) 自动生成，代码里只 `json.load` / `open`，"
        "**不 import 本脚本、不联网**，因此可独立核验，不构成自证循环。")
    add("- 所有 credits 数字均为「按 Tavily 官方计费规则推算」，不是账单；本项目从未查询或记录真实扣费。")
    add("")
    add("## 2. 可写进简历的数字")
    add("")
    SAMPLES = {
        "A": lambda: (
            f"样本：公司 `{show(field(data['live_run'], 'company'))}`，"
            f"`app_mode={show(field(data['live_run'], 'config.app_mode'))}`，"
            f"真实报告 **{show(len({field(data['live_run'], 'company')}))} 份**"
            "（该文件只记录一次运行）。所有数字来自同一次运行，不得外推成总体表现。"
        ),
        "D": lambda: (
            f"样本：{v('F32')} 家公司、{v('F33')} 条人工核验标准答案（用户逐条复核）；"
            f"额度以 `evals/credits_ledger.json` 为准，累计 {v('F38')}。"
            "这批数据是 S10 修复后重跑的，与 A 组的单家报告不可混算。"
        ),
    }
    for i, (gid, title, _) in enumerate(GROUPS, start=1):
        add(f"### 2.{i} {gid} 组｜{title}")
        add("")
        if gid in SAMPLES:
            add(SAMPLES[gid]())
            add("")
        L += fact_table(data, gid)
        add("")
    add("## 3. 简历可用措辞（按编号）")
    add("")
    for gid, _, title in GROUPS:
        add(f"**{title}**")
        add("")
        for x in f:
            if x.group != gid:
                continue
            add(f"- `{x.fid}` {x.resume.format(v=show(x.value(data)))}")
            add(f"  - 边界：{x.note}")
        add("")
    add("> 措辞里出现的每个数值都由对应编号的字段插值生成；"
        "别把两个编号的数字拼成一句未经验证的复合指标（例如「准确率」「提升」）。")
    add("")
    add("## 4. 禁写清单（同样给出处）")
    add("")
    add("| 禁止写法 | 事实 | 出处 | 为什么 |")
    add("|---|---|---|---|")
    for bad, fact, src, why in banned_rows():
        add(f"| {bad} | {fact} | {src} | {why} |")
    add("")
    add("## 5. 未测清单（一律不得写进简历）")
    add("")
    add(f"- 真实准确率、幻觉率、引用可追溯率、p95 延迟、成本单价：**{NOT_MEASURED}**。")
    add(f"- 依据：`evals/live_score.json` → `metric_boundary` 〔`{file_commit(FILES['live_score'])}`〕；"
        f"`evals/live_run.json` → `llm_usage.total_cost_usd` 为 `{show(field(data['live_run'], 'llm_usage.total_cost_usd'))}` "
        f"〔`{file_commit(FILES['live_run'])}`〕。")
    add(f"- 完整对比见 `docs/LIVE_REPORT.md` 〔`{file_commit('docs/LIVE_REPORT.md')}`〕；"
        "fixture 侧有值、真机侧未测，两者不可相减。")
    add(f"- 累计额度仍为 `{v('F01')}` / `{v('F02')}` credits；本阶段未新增任何调用。")
    add("")
    add("## 6. 复现机制")
    add("")
    add("1. `evals/build_resume_evidence.py` 的 `Fact` 持有 `key/path`；"
        "`expr_from_path()` 把同一路径翻译成 `d[\"a\"][\"b\"]`，拼成独立的 `python -c` 命令。")
    add("2. `--verify` 对每条数字**真的起一个进程执行该命令**，"
        "把 stdout 与产物取值逐字比对（两边都用 `json.dumps`，bool/null 不会走样）。")
    add("3. `tests/test_s8_resume_evidence.py` 再做一遍同样的事，并逐条用 "
        "`git show <commit>:<文件>` 回到台账标注的版本重算该字段——"
        "「这个数字在那个 commit 里就有」能被机器验证，而不只是写着一行 hash。")
    add(f"4. 当前共 **{len(f)}** 条可复现数字、**{len(banned_rows())}** 条禁写规则；"
        "这两个计数也由列表长度生成，不是手填。")
    add("")
    add("## 7. 状态")
    add("")
    add(f"- 本文生成：**{blocked}** 次外部连接、**0** 次模型请求、**0** Tavily credits。")
    add("- **S9 已完成**：`docs/RESUME.md` 的每条描述都按本表编号插值，"
        "`tests/test_s9_resume.py` 校验「简历里出现的每个数字都来自本表」。")
    add("- 真实效果指标仍为未测；本表只保证「写出来的数字查得到」，不保证「系统效果好」。")
    return "\n".join(L) + "\n"


def main() -> int:
    from evals.run_eval import eval_offline_guard

    args = sys.argv[1:]
    verify_only = "--verify" in args
    record_only = "--record-commits" in args
    with eval_offline_guard("S8.6 出处表生成") as attempts:
        if record_only:
            commits = record_commits()
            COMMITS_PATH.write_text(
                json.dumps(commits, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"[S8.6] 已登记 {len(commits)} 个文件的 commit -> "
                  f"{COMMITS_PATH.relative_to(ROOT).as_posix()}")
            return 0
        data = load_inputs()
        if verify_only:
            rows = run_verification(data)
            for r in rows:
                mark = "PASS" if r["ok"] else "FAIL"
                print(f"[{mark}] {r['fid']} {r['label']}: {r['actual']}")
                if not r["ok"]:
                    print(f"       expected={r['expected']} rc={r['returncode']} {r['stderr']}")
            failed = [r for r in rows if not r["ok"]]
            print(f"[S8.6 verify] {len(rows) - len(failed)} / {len(rows)} 条复现命令通过")
            return 1 if failed else 0
        text = render(data, blocked=len(attempts))
    assert not attempts, f"生成过程中出现外部连接，拒绝写文档：{attempts!r}"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"[S8.6] 0 调用生成 -> {OUTPUT.relative_to(ROOT).as_posix()} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
