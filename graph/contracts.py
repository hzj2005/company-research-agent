"""S5 结构化输出契约（对应 `docs/PROJECT_PLAN.md` 5.1）。

用 `with_structured_output(PydanticModel)` 取代自由文本 bullet，禁止裸 `json.loads`。
`extra="forbid"` 是刻意的：模型多塞字段必须当场报错并触发重试，而不是被静默吞掉。

注意边界：这里的 `source_url` 非空只是**形式约束**；「来源内容确实支持 claim」
是 `citation_traceability`，需要 judge / golden set，归 S7。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from graph.state import Section


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(_Contract):
    # 字段描述会随 function_calling 的 schema 一起送给模型，比 system prompt 更管用：
    # 只在 system prompt 里写「用中文」，长英文文档一压，模型还是会照抄英文。
    claim: str = Field(
        min_length=1,
        description="用简体中文写的一句话事实；公司名/产品名/数字保留原文，不要翻译掉",
    )
    source_url: HttpUrl = Field(description="该事实的出处 URL，必须来自给定文档")
    confidence: float = Field(ge=0.0, le=1.0, description="该事实被来源直接支持的把握，0~1")


class SectionBrief(_Contract):
    section: Section
    facts: list[Fact] = Field(default_factory=list)
    degraded: bool = False
    degrade_reason: str | None = None


class ResearchBrief(_Contract):
    company: str = Field(min_length=1)
    sections: list[SectionBrief]
    degraded_sections: list[str] = Field(default_factory=list)


# ---- V2 专项契约（PROJECT_PLAN_V2.md S3；仅定义，尚未接入图）--------------
# 这些契约供 S4/S5 的专职 Agent 使用。此刻不切换 fixture stub、不改报告渲染，
# 因此现有流程完全不受影响；接入由 S4/S5 各节点完成。

class FundingRound(_Contract):
    """财务栏目：单轮融资。金额/年份原样保留，带一句可回溯出处。"""

    round_name: str = Field(min_length=1, description="轮次名，如 A 轮 / B 轮")
    amount: str = Field(min_length=1, description="金额原样，如 5000 万美元，不要换算或改写")
    announced_year: str | None = Field(default=None, description="披露年份，如 2021；原文没有则 None")
    investors: list[str] = Field(default_factory=list, description="投资方名称，原文没有则空列表")
    evidence: Fact = Field(description="支撑本轮融资的那条事实（含 source_url）")


class RevenueInfo(_Contract):
    """财务栏目：收入模式。与融资分开，避免塞进同一自由文本 fact。"""

    model: str = Field(min_length=1, description="收入模式描述，如按席位订阅")
    evidence: Fact = Field(description="支撑该收入模式的事实")


class Competitor(_Contract):
    """行业栏目：竞品，带分层（直接 / 替代 / 相邻）。"""

    name: str = Field(min_length=1, description="竞品名，已归一化（Obsidian / obsidian.md 视为同一家）")
    tier: Literal["direct", "substitute", "adjacent"] = Field(
        description="direct=直接竞品；substitute=间接替代；adjacent=相邻玩家"
    )
    # 分层来源：词表标注=False（有据），句式抽取默认 direct=True（推断，须显式留痕）
    tier_inferred: bool = False
    evidence: Fact = Field(description="支撑'这是竞品'的事实")


class MatrixCell(_Contract):
    """对比矩阵的一格：内容必须是搬运的原文事实，禁止生成新判断。"""

    dimension: str = Field(min_length=1, description="对比维度，如 部署 / 定价")
    company: str = Field(min_length=1, description="被描述的公司/竞品名")
    text: str = Field(min_length=1, description="从已有 fact 搬运的原文事实，不生成推断")
    source_url: HttpUrl = Field(description="指向原文的 URL，必须来自给定文档")


class ComparisonMatrix(_Contract):
    """行业栏目：positioning 节点产物。只有事实格，没有'谁更强'的结论。"""

    company: str = Field(min_length=1)
    cells: list[MatrixCell] = Field(default_factory=list)
    # 无公开依据的维度不脑补，记在这里
    missing: list[str] = Field(default_factory=list, description="无公开依据的维度名")
