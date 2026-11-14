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
    claim: str = Field(min_length=1)
    source_url: HttpUrl
    confidence: float = Field(ge=0.0, le=1.0)


class SectionBrief(_Contract):
    section: Section
    facts: list[Fact] = Field(default_factory=list)
    degraded: bool = False
    degrade_reason: str | None = None


class ResearchBrief(_Contract):
    company: str = Field(min_length=1)
    sections: list[SectionBrief]
    degraded_sections: list[str] = Field(default_factory=list)
