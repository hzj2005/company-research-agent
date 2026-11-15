"""S5 结构化输出契约（对应 `docs/PROJECT_PLAN.md` 5.1）。

用 `with_structured_output(PydanticModel)` 取代自由文本 bullet，禁止裸 `json.loads`。
`extra="forbid"` 是刻意的：模型多塞字段必须当场报错并触发重试，而不是被静默吞掉。

注意边界：这里的 `source_url` 非空只是**形式约束**；「来源内容确实支持 claim」
是 `citation_traceability`，需要 judge / golden set，归 S7。
"""

from __future__ import annotations

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
