"""R8-P1：意图路由节点——把「一句话」翻译成「公司 + 要跑哪几个栏目」。

职责只有判定，**不负责派发**：派发仍由 orchestrator 用 `Send` 完成（P2 才接线）。

两个入口，行为刻意不同：

- `user_message` 为空（表单 / CLI / 现有 API / 评测）→ 四栏全选，`source=default_full`，
  **不调模型**。这样既有路径与评测基线零漂移。
- `user_message` 非空 → live 走 LLM 结构化输出；fixture / 无 key / 调用失败走确定性
  规则兜底。规则判不出范围时**追问**（用户 2026-11-18 决策：不默认全跑）。

为什么路由放在图里而不是 API 层：能被单测覆盖、能在轨迹里留痕、评测能算路由准确率。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config.loader import Settings

logger = logging.getLogger(__name__)

SECTION_ORDER: tuple[str, ...] = ("company", "industry", "financial", "news")

SECTION_LABELS: dict[str, str] = {
    "company": "公司概况",
    "industry": "行业竞争",
    "financial": "财务融资",
    "news": "新闻动态",
}

ClarifyKind = Literal["company", "scope", "followup"]

# 「全都要」类说法
_ALL_WORDS = (
    "全部", "全都", "全都要", "都要", "全看", "都看", "全面", "完整",
    "四个都", "四块都", "整个报告", "全面调研", "完整调研",
)

# 栏目 -> 触发词。宁可少收，不可错收：判不出就追问，不猜。
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "company": (
        "公司概况", "公司介绍", "公司简介", "公司背景", "背景", "介绍",
        "做什么", "业务", "产品", "成立", "总部", "规模", "员工",
    ),
    "industry": (
        "行业", "市场", "竞品", "竞争", "对手", "份额", "格局", "赛道", "对标", "同类",
    ),
    "financial": (
        "财务", "融资", "营收", "收入", "估值", "轮次", "财报", "利润", "现金流", "投资人",
    ),
    "news": (
        "新闻", "动态", "消息", "最近", "近期", "发布", "合作", "收购", "进展", "公告",
    ),
}

_NEG_PREFIX = ("不要", "不看", "不用", "不需要", "除了", "去掉", "不含", "别")

# 指代词：抽到这些说明用户没说公司名
_PRONOUNS = {
    "那家", "这家", "那个", "这个", "那些", "这些", "它", "它们", "他", "她",
    "我", "我们", "对方", "该", "此",
}

_LATIN_NAME = re.compile(r"[A-Za-z][A-Za-z0-9&.\-]*(?:\s+[A-Za-z][A-Za-z0-9&.\-]*)*")
# 两种中文句式，按顺序尝试：
#   ① 「查/看/了解 X 的…」——动词在前
#   ② 「X 的财报/新闻/行业…」——动词全省略（"只看特斯拉的财报" 走①，"特斯拉的财报" 走②）
_CN_PATTERNS = (
    re.compile(
        r"(?:查查|查一下|查|了解|看看|看|调研|研究|分析|搜|关注)\s*(?:一下|下)?\s*"
        r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}?)(?:的|最近|近期|公司|$)"
    ),
    re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9]{2,12})的"
        r"(?:财报|财务|融资|估值|营收|新闻|动态|行业|竞品|市场|公司|业务|产品)"
    ),
    # ③ 「X 最近/近期…」——没有动词也没有「的」
    re.compile(r"([\u4e00-\u9fa5A-Za-z0-9]{2,12})(?:最近|近期)"),
)
# 抽到这些说明不是公司名（时间/指代/限定词），一律当没抽到
_CN_STOPWORDS = {
    "最近", "近期", "今年", "去年", "目前", "现在", "今天", "整体", "大概",
    "主要", "一些", "所有", "全部", "相关", "其他", "他们", "我们", "你们",
    "什么", "啥", "哪些", "哪个", "怎么样", "如何", "详情", "情况", "一点",
}



class RouteDecision(BaseModel):
    """路由判定结果。字段与 LLM 结构化输出共用，便于两条路径互相替换。"""

    company: str | None = Field(default=None, description="要调研的公司；判不出留空")
    sections: list[str] = Field(default_factory=list, description="要跑的栏目 key")
    need_clarify: bool = Field(default=False, description="是否需要追问用户")
    clarify_kind: ClarifyKind | None = Field(default=None, description="缺公司/缺范围/指代不明")
    question: str = Field(default="", description="追问话术")
    reason: str = Field(default="", description="一句话判定理由，写进轨迹")


RouteFn = Callable[[str, str, Settings], Awaitable[RouteDecision]]


def _negated(message: str, keyword: str) -> bool:
    """关键词前面 6 个字内出现否定词 → 视为「排除这个栏目」。"""
    for match in re.finditer(re.escape(keyword), message):
        prefix = message[max(0, match.start() - 6):match.start()]
        if any(neg in prefix for neg in _NEG_PREFIX):
            return True
    return False


def rule_sections(message: str) -> tuple[list[str], list[str], bool]:
    """规则判定：(选中, 被排除, 是否说了「全都要」)。"""
    wants_all = any(word in message for word in _ALL_WORDS)
    picked: list[str] = []
    excluded: list[str] = []
    for section in SECTION_ORDER:
        hits = [kw for kw in _KEYWORDS[section] if kw in message]
        if not hits:
            continue
        if all(_negated(message, kw) for kw in hits):
            excluded.append(section)
        else:
            picked.append(section)
    if wants_all:
        # 「融资、竞品、新闻都要」= 点名的那几块全要，不是四栏全要；
        # 只有没点名任何栏目时（「全都要」「全面调研」）才展开成四栏。
        picked = picked or [s for s in SECTION_ORDER if s not in excluded]
    elif not picked and excluded:
        # 只说「不要新闻」= 其余三栏
        picked = [s for s in SECTION_ORDER if s not in excluded]
    return picked, excluded, wants_all


def guess_company(message: str) -> str:
    """从一句话里猜公司名。猜不准就返回空串，由调用方追问。

    只做保守启发：优先取英文名（Notion / OpenAI / Tesla 这类最常见），
    再退到「查一下 X 的…」句式。抽到指代词（那家/这个/它）一律当没抽到。
    """
    for match in _LATIN_NAME.finditer(message):
        token = match.group(0).strip(" .,，。!！?？")
        if len(token) >= 2 and not token.isdigit():
            return token
    for pattern in _CN_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        token = match.group(1).strip()
        if not token or token in _PRONOUNS or token in _CN_STOPWORDS:
            continue
        # 「健身行业」「特斯拉公司」→ 去掉类目后缀，留下主体
        for suffix in ("行业", "领域", "赛道", "市场", "公司"):
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                token = token[: -len(suffix)]
                break
        if token:
            return token
    return ""


def _normalize_sections(raw: list[str] | tuple[str, ...] | None) -> list[str]:
    """只认四个固定 key，去重，按配置顺序输出。非法值直接丢弃（不猜同义词）。"""
    wanted = {str(s).strip().lower() for s in (raw or [])}
    return [s for s in SECTION_ORDER if s in wanted]


def clarify_options() -> list[dict[str, str]]:
    """追问时给可点选项——用户不该被迫记住栏目名。"""
    return [
        *({"key": s, "label": SECTION_LABELS[s]} for s in SECTION_ORDER),
        {"key": "all", "label": "全都要"},
    ]


def rule_route(message: str, company_hint: str = "") -> RouteDecision:
    """确定性规则兜底：fixture、无 key、LLM 失败都走这里。"""
    picked, _excluded, _wants_all = rule_sections(message)
    company = (company_hint or "").strip() or guess_company(message)

    if not company:
        return RouteDecision(
            company=None,
            sections=[],
            need_clarify=True,
            clarify_kind="company",
            question="你想调研哪家公司？给我公司名或官网链接就行。",
            reason="消息里没有识别到公司主体",
        )
    if not picked:
        return RouteDecision(
            company=company,
            sections=[],
            need_clarify=True,
            clarify_kind="scope",
            question=f"想看 {company} 的哪几块？",
            reason="有公司主体但没给范围，按约定先追问",
        )
    return RouteDecision(
        company=company,
        sections=picked,
        need_clarify=False,
        reason=f"规则命中：{'、'.join(SECTION_LABELS[s] for s in picked)}",
    )


_SYSTEM = """你在判断用户想调研什么。只输出结构化结果，不要回答问题本身。

可选栏目（只能从这四个 key 里选）：
- company   公司概况：公司是什么、做什么业务、成立时间、总部、规模
- industry  行业竞争：所处行业、市场规模、竞品、份额、格局
- financial 财务融资：营收、利润、融资轮次、金额、估值、投资方
- news      新闻动态：近期发布、合作、收购、人事、公告

判定规则：
0. 已知公司 = 「{known_company}」。只要它不是「（用户未提供）」，就把它当作公司主体，
   不要因为这句话里没重复公司名就追问公司（多轮对话里用户常用「那新闻呢」）。
1. 句子里出现任何栏目线索就选上对应 key，哪怕只有几个字：
   「那新闻呢」→ news；「那财务呢」→ financial。
2. 用户明确点名了哪几块，就只选那几块；可以多选。
3. 用户说「全部/全面/完整调研」→ 四栏全选；若同时点名了栏目（如「融资和新闻都要」），
   只选点名的那几栏。
4. 用户明确排除某块（「不要新闻」）→ 选其余栏目。
5. 既没有已知公司、句子里也判不出公司 → need_clarify=true，clarify_kind=company。
6. 公司已知但**完全没有**栏目线索（如「帮我查一下 Notion」）→ need_clarify=true，
   clarify_kind=scope，question 用一句话问「想看哪几块」，不要替用户决定。
7. 不要编造公司名。拿不准就追问，不要猜。"""


async def llm_route_message(
    message: str, company_hint: str, settings: Settings
) -> RouteDecision:
    """LLM 路由：一次结构化调用。校验交给调用方（node），这里只负责拿到原始判定。"""
    from capabilities.llm import make_chat_model

    model = make_chat_model(settings, "research")
    chain = (
        ChatPromptTemplate.from_messages(
            [("system", _SYSTEM), ("human", "{message}")]
        )
        | model.with_structured_output(RouteDecision, method="function_calling")
    )
    out = await chain.ainvoke(
        {"message": message, "known_company": company_hint or "（用户未提供）"}
    )
    if isinstance(out, RouteDecision):
        return out
    return RouteDecision.model_validate(out)


def make_router_node(
    settings: Settings, *, llm_route: RouteFn | None = None, force_rules: bool = False
) -> Any:
    """路由节点工厂。

    `llm_route` 可注入，用于在 0 次真实调用下验证 LLM 路径与校验逻辑。
    未注入且非 live 模式时**不构造模型**（fixture 下没有凭据也不该尝试）。
    """

    async def route(state: dict[str, Any]) -> dict[str, Any]:
        message = str(state.get("user_message") or "").strip()
        company_hint = str(state.get("company") or "").strip()

        # ⓪ API 层（/chat）已经判过 → 直接用，不重复调模型
        if state.get("route_locked") and state.get("requested_sections"):
            sections = _normalize_sections(state.get("requested_sections"))
            meta = {
                "node": "route",
                "source": "locked",
                "company": company_hint,
                "sections": sections,
                "need_clarify": False,
                "clarify_kind": None,
                "reason": "API 层已判定，节点不再调模型",
            }
            return {
                "requested_sections": sections,
                "route_meta": meta,
                "clarify": {},
                "review_notes": [meta],
            }

        # ① 没有自然语言输入 → 完整报告，且不调模型（保持旧路径零成本零漂移）
        if not message:
            sections = list(SECTION_ORDER)
            meta = {
                "node": "route",
                "source": "default_full",
                "sections": sections,
                "company": company_hint,
                "reason": "未提供自然语言输入，按完整报告处理",
            }
            return {
                "requested_sections": sections,
                "route_meta": meta,
                "clarify": {},
                "review_notes": [meta],
            }

        notes: list[dict[str, Any]] = []
        decision: RouteDecision | None = None
        source = "rules"

        active = (
            None
            if force_rules
            else (llm_route or (llm_route_message if settings.app.mode == "live" else None))
        )
        if active is not None:
            try:
                decision = await active(message, company_hint, settings)
                source = "llm"
            except Exception as exc:  # noqa: BLE001 —— 路由失败必须可降级
                logger.warning("路由 LLM 调用失败，降到规则：%s", exc)
                notes.append(
                    {
                        "node": "route",
                        "status": "failed",
                        "via": "llm",
                        "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                    }
                )

        if decision is None:
            decision = rule_route(message, company_hint)
            source = "rules"

        # ② 校验：非法 key 丢弃，去重，按配置顺序
        sections = _normalize_sections(decision.sections)
        # 模型偶尔不回公司名（实测："帮我查一下 Notion" 回了 scope 但 company=null），
        # 这时用同一套启发式补，否则追问话术里没有主体、下一轮也接不上。
        company = (
            company_hint or (decision.company or "") or guess_company(message)
        ).strip()
        # 确定性兜底：模型偶尔漏掉明显的栏目线索（实测「那新闻呢」回了空集合）。
        # 只有主体明确时才兜——连公司都没有的话，补出栏目也不能开跑，仍应追问公司。
        if not sections and company:
            picked, _excluded, _all = rule_sections(message)
            if picked:
                sections = picked

        need_clarify = bool(decision.need_clarify)
        clarify_kind = decision.clarify_kind
        question = (decision.question or "").strip()

        # 公司已知 + 栏目也判出来了 = 该有的信息都有，不该再追问。
        # （多轮场景实测：会话已带公司名，模型仍会因为「那新闻呢」这句话里没有
        #   公司而要求澄清——那是多余的。）
        if company and sections:
            need_clarify = False
            clarify_kind = None
            question = ""

        # 确实要追问，就说明这轮不跑任何子图 —— 栏目集合清空，避免
        # 「既要追问又带着半截范围」的状态被下游误用。
        if need_clarify:
            sections = []

        # 模型说「缺公司」但其实能猜出来 → 降级成「缺范围」，把公司写进追问
        if need_clarify and clarify_kind == "company" and company:
            clarify_kind = "scope"
            question = f"想看 {company} 的哪几块？"
        # 追问范围时，话术里必须带公司名，否则下一轮用户不知道在问谁
        elif need_clarify and clarify_kind == "scope" and company and company not in question:
            question = f"想看 {company} 的哪几块？"

        # LLM 可能给了空集合却忘了标 clarify —— 这里兜住，绝不派发 0 个栏目
        if not sections and not need_clarify:
            if not company:
                need_clarify, clarify_kind = True, "company"
                question = question or "你想调研哪家公司？给我公司名或官网链接就行。"
            else:
                need_clarify, clarify_kind = True, "scope"
                question = question or f"想看 {company} 的哪几块？"

        meta = {
            "node": "route",
            "source": source,
            "company": company,
            "sections": sections,
            "need_clarify": need_clarify,
            "clarify_kind": clarify_kind if need_clarify else None,
            "reason": decision.reason,
        }
        notes.append(meta)

        result: dict[str, Any] = {
            "requested_sections": sections,
            "route_meta": meta,
            "clarify": (
                {
                    "kind": clarify_kind,
                    "question": question,
                    "options": clarify_options(),
                }
                if need_clarify
                else {}
            ),
            "review_notes": notes,
        }
        # 只有原本没有公司时才回写，避免覆盖调用方给的主体
        if not company_hint and company:
            result["company"] = company
        return result

    return route


async def decide_route(
    message: str,
    company_hint: str = "",
    settings: Settings | None = None,
    *,
    llm_route: RouteFn | None = None,
    force_rules: bool = False,
) -> dict[str, Any]:
    """给 API 层用的扁平判定入口（`/chat` 先判、再决定要不要建任务）。

    复用节点本身的逻辑，避免 API 和图各写一套判定；/chat 判定后会把
    `route_locked=True` + `requested_sections` 传给图，图里不再重复调模型。
    """
    if settings is None:
        from config.loader import get_settings

        settings = get_settings()

    node = make_router_node(settings, llm_route=llm_route, force_rules=force_rules)
    out = await node({"company": company_hint, "user_message": message})
    meta = out.get("route_meta") or {}
    clarify = out.get("clarify") or {}
    return {
        "company": out.get("company") or company_hint,
        "sections": list(out.get("requested_sections") or []),
        "need_clarify": bool(clarify),
        "clarify_kind": clarify.get("kind"),
        "question": clarify.get("question") or "",
        "options": clarify.get("options") or [],
        "source": meta.get("source"),
        "reason": meta.get("reason"),
    }
