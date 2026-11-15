"""S11：按岗位方向输出多版简历措辞（0 调用 / 0 credits）。

    uv run python -m evals.build_resume_variants   # 重新生成 docs/RESUME_VARIANTS.md

**核心取舍：只换顺序、选条与解读，不重写事实句。**

三版共用 `evals/build_resume.py` 里的同一批 `Bullet.paste` 原文——那句话是出处表
锚定过的（每个数字都是 `{Fxx}` 占位符，渲染时从产物取值）。如果为每个岗位再手写
一版措辞，同一件事就会出现三种说法，出处表只能管住其中一份，剩下两份随时可能
漂成「没出处的话」。所以差异化放在三个安全的地方：

1. **先说什么**：按岗位关心的问题重排三条的先后；
2. **说哪三条**：从四条里选与该岗位最相关的三条（一页简历一个项目三条够用）；
3. **为什么有用**：每条配一句岗位视角的解读，解读里可以提代码位置与设计取舍，
   但不许引入任何新的数字或效果声明。

红线与 `docs/RESUME.md` 完全一致：模板禁止裸数字、只写做得到的事、保留上游归因。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from evals import build_resume as r
from evals import build_resume_evidence as ev

ROOT = ev.ROOT
OUTPUT = ROOT / "docs" / "RESUME_VARIANTS.md"
BY_TITLE = {b.title: b for b in r.BULLETS}
BULLETS_PER_VARIANT = 3


@dataclass(frozen=True)
class Variant:
    key: str
    role: str
    headline: str
    why: str
    keep: tuple[str, ...]
    angles: dict[str, str]
    avoid: tuple[str, ...]

    def bullets(self) -> tuple[r.Bullet, ...]:
        return tuple(BY_TITLE[t] for t in self.keep)

    def texts(self) -> list[str]:
        return [self.headline, self.why, *self.angles.values(), *self.avoid]

    def fids(self) -> list[str]:
        found: set[str] = set()
        for text in self.texts():
            found |= set(r.PLACEHOLDER.findall(text))
        for b in self.bullets():
            found |= set(b.facts())
        return sorted(found)


def _t(title: str) -> str:
    """按标题取条目，取不到就直接报错（防止改名后静默漏条）。"""
    if title not in BY_TITLE:
        raise KeyError(f"岗位版引用了不存在的条目标题：{title}")
    return title


VARIANTS: tuple[Variant, ...] = (
    Variant(
        key="agent",
        role="Agent 工程（LangGraph / 状态机 / 可恢复编排）",
        headline=(
            "把上游那条一路 `add_edge` 串到底的线性流水线，改造成有分支、有回退、能中断恢复的 "
            "LangGraph 状态机；重点不是「用了 LangGraph」，而是「为什么这里必须用图」。"
        ),
        why=(
            "这个岗位最先追问的是「为什么非要用图」，所以把 `Send` 并行、规则化终止条件、"
            "checkpoint 恢复三条排在最前；额度护栏放中间，说明外部调用不会失控；"
            "真机排障闭环收尾，证明这套编排在真实噪声下也修得动。"
        ),
        keep=(
            _t("图编排与可恢复的人工复核（LangGraph）"),
            _t("真实检索链路与额度纪律"),
            _t("从真机报告定位并修复合成语料测不出的问题"),
        ),
        angles={
            _t("图编排与可恢复的人工复核（LangGraph）"): (
                "重点讲三件事：回环终止靠 `retry_count >= max_retry` 比较，不让模型自述「够了」；"
                "`Send` 是图级并行，没被派发的 analyst 根本不执行；子图用 `input_schema / output_schema` "
                "隔离，避免主图 reducer 重复累加。三句都能当场指到代码。"
            ),
            _t("真实检索链路与额度纪律"): (
                "Agent 工程的一半是护栏：三重 opt-in 默认全关、`CallBudget` 在发请求前扣额度、"
                "sha256 缓存命中不扣、dry-run 用一调用就抛错的哨兵兜底——装上 key 也调不动。"
            ),
            _t("从真机报告定位并修复合成语料测不出的问题"): (
                "完整的排障闭环：报告里发现异常 → 回看缓存原文 → 定位到两处问题同源、是另一家同名公司 → "
                "加交易所代码绑定与官网域名一致性两道规则 → 用真实语料回放确认无误杀。"
            ),
        },
        avoid=(
            "别讲成「多智能体自主协同」或「自主规划」：这里没有 planner / reflection 式的自由编排，"
            "只有固定拓扑加规则分支，说大了会被当场追问到答不上来。",
            "别写「支持任意工具调用」：工具只有检索与结构化抽取两个，没有通用 tool 注册表。",
        ),
    ),
    Variant(
        key="rag",
        role="RAG / 检索增强生成（检索、抽取、引用与评测）",
        headline=(
            "检索增强的调研报告生成：真实网页检索 + Pydantic 结构化抽取 + 分层评测，"
            "把「说错」和「没说」分开计量，而不是揉成一个「准确率」。"
        ),
        why=(
            "RAG 岗真正会追问两件事：「检索到错的东西怎么办」「引用到底能不能核」。"
            "所以实体消歧与冲突标注排第一，评测口径第二，检索侧工程第三——评测那一条恰好回答了"
            "「你怎么知道自己的引用是真的」。"
        ),
        keep=(
            _t("从真机报告定位并修复合成语料测不出的问题"),
            _t("人工核验标准答案与可回归的评测台"),
            _t("真实检索链路与额度纪律"),
        ),
        angles={
            _t("从真机报告定位并修复合成语料测不出的问题"): (
                "RAG 的典型失败不是「检索不到」，而是「检索到同名不同实体」，以及「两份来源各说一个数」。"
                "这里用标题交易所代码绑定 + 跨文档官网域名一致性做消歧，同栏目多值冲突显式标注、"
                "不替读者取舍——因为按置信度选一条会正好留下错的那个。"
            ),
            _t("人工核验标准答案与可回归的评测台"): (
                "评测口径是最容易糊弄的地方：人工核验标准答案、AI 语义 judge、证据句逐字校验；"
                "再用 A/B 关掉行内引用，让引用分归零而事实准确率不动，证明 fixture 满分只是流程契约分。"
            ),
            _t("真实检索链路与额度纪律"): (
                "检索侧工程：缓存 key 由 query / section / 条数 / depth / topic 取 sha256，"
                "命中直接返回文档、不扣额度，所以一次真实调用之后能离线反复复现同一批检索结果。"
            ),
        },
        avoid=(
            "本项目是网页检索，不是向量库：不要写「召回率」「向量索引」「chunk 策略」，"
            "这三样既没实现也没测。",
            "别写「引用可追溯率」：引用层明确标了不可用（换过 URL 的条目没有重抓），只写「行内引用带编号、可点回原文」。",
        ),
    ),
    Variant(
        key="backend",
        role="后端 / 服务化（外部依赖、预算、持久化与生命周期）",
        headline=(
            "把上游自带的 FastAPI `/research` 入口从旧的线性调用切到新图：每次请求独立 thread_id + "
            "SQLite checkpoint 续跑，外部调用走预算与磁盘缓存，出问题能凭落盘产物定位到具体请求。"
        ),
        why=(
            "后端岗看三件事：外部依赖失控怎么办、进程重启会怎样、跑测试会不会偷偷花钱。"
            "所以额度纪律打头，checkpoint 与客户端生命周期居中，评测进 CI 收尾。"
        ),
        keep=(
            _t("真实检索链路与额度纪律"),
            _t("图编排与可恢复的人工复核（LangGraph）"),
            _t("人工核验标准答案与可回归的评测台"),
        ),
        angles={
            _t("真实检索链路与额度纪律"): (
                "外部依赖一律当不可信处理：三重开关是「与」关系，任一不满足直接抛 `LiveRetrievalDisabled`；"
                "`CallBudget` 在发请求前扣额度、用尽抛错不重试；缓存 key 取参数 sha256，命中不扣额度。"
            ),
            _t("图编排与可恢复的人工复核（LangGraph）"): (
                "持久化选型没为了好看硬凑：异步节点下同步 `SqliteSaver` 的 `aget_tuple` 会抛 "
                "`NotImplementedError`，PostgresSaver 未实现就明确抛错。另外长驻入口每来一个请求会泄漏一个 "
                "`httpx.AsyncClient`，改成把所有权交给一次图运行、退出时 `aclose()`，并有生命周期测试盯着。"
            ),
            _t("人工核验标准答案与可回归的评测台"): (
                "评测进 CI：fixture 回归零外部调用，另装 socket 禁网守卫，让「测试误耗额度」"
                "在物理上不可能发生，而不是靠自觉。"
            ),
        },
        avoid=(
            "不要写「高并发 / QPS / 分布式部署」：这是单机单进程的本地复现，没压测、没上线、没有多副本。",
            "不要把 checkpoint 说成「分布式任务队列」：它就是 SQLite 落盘 + 线程绑定，能力边界到「跨进程续跑」为止。",
        ),
    ),
)


def fact_values(data: dict[str, Any]) -> dict[str, str]:
    return r.fact_values(data)


def render(data: dict[str, Any], blocked: int = 0) -> str:
    values = fact_values(data)
    upstream = ev.upstream_commit()
    L: list[str] = []
    add = L.append

    add("# 按岗位出多版简历措辞（S11）")
    add("")
    add("> **一句话**：同一份事实、三种排法。三条正文一律复用 `docs/RESUME.md` 里那句"
        "出处表锚定过的原文，只换「先说什么」「说哪三条」和「为什么这对该岗位有用」——"
        "差异化不靠改事实句，靠换视角。")
    add("")
    add(f"**归因不变**：基于 `guy-hartstein/company-research-agent`（Apache-2.0，上游 commit "
        f"`{upstream}`）二次开发；三版都不写「独立开发」「从零自研」。")
    add("")
    add("| 岗位 | 排序（从先到后） | 主要引用编号 |")
    add("|---|---|---|")
    for v in VARIANTS:
        order = " → ".join(f"「{t.split('（')[0]}」" for t in v.keep)
        refs = "、".join(f"`F{x}`" for x in v.fids())
        add(f"| {v.role.split('（')[0]} | {order} | {refs} |")
    add("")
    add("> 三版都不新增测量值。表里的编号指向 `docs/RESUME_EVIDENCE.md`，"
        "每个值都能用一条命令复现；复现不了的不写。")
    add("")

    for i, v in enumerate(VARIANTS, start=1):
        add(f"## {i}. {v.role}")
        add("")
        add(f"**一句话定位**：{r.fill(v.headline, values)}")
        add("")
        add(f"**为什么这么排**：{r.fill(v.why, values)}")
        add("")
        add("**可直接粘贴（三条，按此顺序）**：")
        add("")
        for b in v.bullets():
            add(f"- **{b.title}**：{r.fill(b.paste, values)}")
        add("")
        add("**每条对该岗位的价值（面试自述，不写进简历）**：")
        add("")
        for b in v.bullets():
            add(f"- 「{b.title.split('（')[0]}」——{r.fill(v.angles[b.title], values)}")
        add("")
        add("**这一版不要写**：")
        add("")
        for a in v.avoid:
            add(f"- {r.fill(a, values)}")
        add("")
        add("代码位置：" + "、".join(
            f"`{c}`" for b in v.bullets() for c in b.code
        ) + "。")
        add("")

    add("## 4. 三版共用的底线")
    add("")
    add("- 正文与数字只来自 `docs/RESUME.md` 与 `docs/RESUME_EVIDENCE.md`；本文只重排、不新增测量。")
    add("- 三版都不写准确率 / 幻觉率 / 引用可追溯率 / p95 延迟 / 成本单价：**未测**。")
    add("- 三版都不写「独立开发 / 从零自研 / 上线 / 甲方 / 用户量 / 提升 X%」：没有这些事实。")
    add("- 换岗位可以换顺序与解读，不能换事实；某个岗位需要的卖点这里没有，就是没有，不许补一句。")
    add("")
    add("## 5. 复现与护栏")
    add("")
    add("```bash")
    add("uv run python -m evals.build_resume_variants        # 重新生成本文（0 调用）")
    add("uv run pytest -q tests/test_s11_resume_variants.py  # 护栏：裸数字 / 编号存在 / 顺序真的不同")
    add("uv run python -m evals.build_resume                 # 单版长文（含十八条面试追问）")
    add("uv run python -m evals.build_resume_evidence --verify   # 逐条执行出处表里的复现命令")
    add("```")
    add("")
    add("## 6. 状态")
    add("")
    add(f"- 本文生成：**{blocked}** 次外部连接、**0** 次模型请求、**0** Tavily credits。")
    add(f"- 共 **{len(VARIANTS)}** 个岗位方向、每版 **{BULLETS_PER_VARIANT}** 条，"
        f"覆盖 **{len({t for v in VARIANTS for t in v.keep})}** 个不同条目（共 {len(r.BULLETS)} 条）。")
    add("- 面试追问清单不按岗位重写：那十八条在 `docs/RESUME.md` §3，通用。")
    return "\n".join(L) + "\n"


def main() -> int:
    from evals.run_eval import eval_offline_guard

    with eval_offline_guard("S11 岗位版简历生成") as attempts:
        data = ev.load_inputs()
        text = render(data, blocked=len(attempts))
    assert not attempts, f"生成过程中出现外部连接，拒绝写文档：{attempts!r}"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"[S11] 0 调用生成 -> {OUTPUT.relative_to(ROOT).as_posix()} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
