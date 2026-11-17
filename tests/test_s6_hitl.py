"""S6 HITL 验收：图内 `interrupt()` + 跨 session `Command(resume=...)`。

全程 fixture、0 次真实 Tavily / 模型调用。两次 `run_research` 各自新建
`CheckpointSession`，等价于「关掉进程再重开」，验证 S2 的持久化不是摆设。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from conftest import assert_report_shape

from capabilities.retrieval import make_document_tool
from config.loader import apply_overrides, get_settings
from graph.builder import build_graph
from graph.run import run_research

# R3：主图 5 节点（消歧/判定/回退下沉子图）
BASE_NODES = {"grounding", "research", "briefing"}
ABSTAIN = "该类信息未找到公开依据"


def _review_settings(**extra: object):
    return apply_overrides(
        get_settings(),
        {"features.human_review": True, "features.auto_approve_review": False, **extra},
    )


def _start(company: str, db: Path):
    return asyncio.run(
        run_research(company, _review_settings(), db, collect_trace=True)
    )


def _resume(company: str, db: Path, decision: object):
    return asyncio.run(
        run_research(company, _review_settings(), db, collect_trace=True, resume=decision)
    )


def test_default_graph_has_no_review_node_and_report_is_unchanged(tmp_path: Path) -> None:
    """开关默认关：主图严格 7 节点，报告与 S5 逐字一致（`test_s4_subgraph.py:97` 依赖）。"""
    s = get_settings()
    assert s.features.human_review is False
    assert set(build_graph(s, make_document_tool(s)).nodes.keys()) == BASE_NODES

    state, _ = asyncio.run(run_research("Notion", s, tmp_path / "default.db"))
    assert_report_shape(state["report"])
    assert "_interrupt" not in state
    assert state["review_decision"] == {}


def test_switch_on_adds_node_but_auto_approve_never_interrupts(tmp_path: Path) -> None:
    s = apply_overrides(
        get_settings(),
        {"features.human_review": True, "features.auto_approve_review": True},
    )
    assert "human_review" in build_graph(s, make_document_tool(s)).nodes
    state, trace = asyncio.run(
        run_research("Notion", s, tmp_path / "auto.db", collect_trace=True)
    )
    assert "_interrupt" not in state
    assert state["review_decision"]["note"] == "auto_approved"
    assert "human_review" in trace
    assert_report_shape(state["report"])


def test_real_interrupt_pauses_before_briefing(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    state, trace = _start("Notion", db)

    assert "_interrupt" in state, "auto_approve=false 时必须真的暂停"
    payload = state["_interrupt"]["payload"]
    assert payload["company"] == "Notion"
    assert payload["sections"] == ["company", "industry", "financial", "news"]
    assert "decision_schema" in payload
    assert state["_interrupt"]["thread_id"]
    assert state["report"] == "", "中断时绝不能已经成稿"
    assert "__interrupt__" in trace
    assert "briefing" not in trace


def test_review_payload_carries_evidence_to_decide_on(tmp_path: Path) -> None:
    """复核面板必须带证据摘要，否则复核人只能看到一个引用总数 = 盲批。

    只给「共 N 条引用」，人既判断不了证据够不够，也定不了该拒答哪一栏，
    这个闸门就没有意义。所以 payload 里必须带每栏的证据（标题/来源/摘录）。
    """
    db = tmp_path / "evidence.db"
    state, _ = _start("Notion", db)
    payload = state["_interrupt"]["payload"]

    assert "evidence" in payload, "复核 payload 必须带证据摘要"
    evidence = payload["evidence"]
    assert set(evidence) == set(payload["sections"])

    company_items = evidence["company"]
    assert company_items, "公司概况栏目必须有证据，否则人无从判断"
    first = company_items[0]
    assert set(first) == {"title", "url", "score", "snippet"}
    assert first["url"], "证据必须带来源链接，人要能自己去核"
    assert first["snippet"], "证据必须带正文摘录，光有标题判断不了"
    # 摘录要截断，不能把整篇正文塞进 payload（它要进 checkpoint、还要过 SSE）
    assert all(len(item["snippet"]) <= 260 for item in company_items)


def test_review_payload_evidence_matches_what_would_be_reported(tmp_path: Path) -> None:
    """面板里给的证据，必须和最终报告会用的证据是同一批。

    不一致的话会出现「面板看着证据很足，报告却写未找到公开依据」这种更糟的情况。
    """
    db = tmp_path / "consistency.db"
    state, _ = _start("Notion", db)
    evidence = state["_interrupt"]["payload"]["evidence"]

    approved_state, _ = _resume("Notion", db, {"approved": True})
    report = approved_state["report"]

    for section, items in evidence.items():
        if not items:
            continue
        # 报告里该栏目要么有正文（用了这些证据），要么明确拒答
        assert section not in approved_state.get("degraded_sections", [])
    assert ABSTAIN not in report, "证据齐的栏目不该被拒答"


def test_resume_in_a_new_session_completes_the_report(tmp_path: Path) -> None:
    """两次 run_research = 两个独立 CheckpointSession，等价跨进程恢复。"""
    db = tmp_path / "resume.db"
    _start("Linear", db)
    state, trace = _resume("Linear", db, {"approved": True, "note": "looks good"})

    assert "_interrupt" not in state
    assert_report_shape(state["report"])
    assert state["review_decision"]["approved"] is True
    assert state["review_decision"]["note"] == "looks good"
    assert "human_review" in trace and "briefing" in trace
    # 前半段节点从 checkpoint 恢复，没有重跑
    assert "research" not in trace


def test_reject_sections_changes_only_that_section(tmp_path: Path) -> None:
    db = tmp_path / "partial.db"
    _start("Notion", db)
    state, _ = _resume(
        "Notion", db,
        {"approved": True, "rejected_sections": ["news"], "note": "新闻来源存疑"},
    )
    report = state["report"]
    assert state["degraded"] is True
    assert "news" in state["degraded_sections"]
    assert "company" not in state["degraded_sections"]
    assert ABSTAIN in report
    assert "Notion 产品概览" in report, "未拒答栏目必须照常出稿"
    assert "## 新闻动态\n\n- " + ABSTAIN in report
    assert_report_shape(report)
    news_body = report.split("## 新闻动态", 1)[-1].split("## References", 1)[0]
    assert not [ln for ln in news_body.splitlines() if ln.startswith("- ") and ABSTAIN not in ln], (
        "被拒栏目只剩拒答行，不能残留任何原始事实行"
    )
    assert any(n["node"] == "human_review" and n["status"] == "rejected"
               for n in state["review_notes"])


def test_reject_all_abstains_without_fabrication(tmp_path: Path) -> None:
    db = tmp_path / "reject.db"
    _start("Notion", db)
    state, _ = _resume("Notion", db, {"approved": False, "note": "整体不可用"})
    report = state["report"]

    assert set(state["degraded_sections"]) == {"company", "industry", "financial", "news"}
    assert report.count(ABSTAIN) == 4
    assert "https://" not in report, "全部拒答时 References 必须为空，不能留无引用结论"
    assert "（合成）" not in report, "不得残留任何合成事实"


def test_invalid_resume_value_fails_safe_and_unknown_sections_are_filtered(
    tmp_path: Path,
) -> None:
    db = tmp_path / "invalid.db"
    _start("Notion", db)
    state, _ = _resume("Notion", db, "not-a-dict")
    assert state["review_decision"]["invalid"] is True
    assert state["review_decision"]["approved"] is False
    assert set(state["degraded_sections"]) == {"company", "industry", "financial", "news"}

    db2 = tmp_path / "whitelist.db"
    _start("Notion", db2)
    state2, _ = _resume(
        "Notion", db2,
        {"approved": True, "rejected_sections": ["news", "evil-section", "news"]},
    )
    assert state2["degraded_sections"] == ["news"], "非法栏目必须被白名单过滤且去重"


def test_review_mode_still_makes_zero_external_calls(tmp_path: Path) -> None:
    """S6 不引入任何网络路径：复核 + 恢复全程只碰本地 SQLite 与 mock HTTP。"""
    import socket
    from unittest.mock import patch

    original = socket.socket.connect
    attempts: list[object] = []

    def guarded(self: socket.socket, address: object, *a: object, **kw: object) -> object:
        host = str(address[0]) if isinstance(address, tuple) and address else str(address)
        if host.startswith("127.") or host in ("::1", "localhost"):
            return original(self, address, *a, **kw)
        attempts.append(address)
        raise AssertionError(f"外部连接 {address!r}：S6 应 0 次外部调用")

    db = tmp_path / "offline.db"
    with patch.object(socket.socket, "connect", guarded):
        _start("Notion", db)
        state, _ = _resume("Notion", db, {"approved": True})
    assert_report_shape(state["report"])
    assert attempts == []
    assert socket.socket.connect is original


def test_api_review_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """API 级 HITL 闭环：POST /research 停在 waiting_review，POST /review 续跑成稿。

    这是 S13 接通前端的后端护栏——之前开开关从前端发起会直接 failed（缺 resume 接口），
    这条用例钉死「能暂停、能提交决定、能落库」三段都不再退化。
    """
    import time

    from fastapi.testclient import TestClient

    import application
    from backend.classes.state import job_status

    review_settings = _review_settings()

    # 两个进程内入口（research 后台任务 / review 续跑）必须读同一份 HITL 配置、
    # 落同一个临时 checkpoint，否则续跑拿不到存档。
    monkeypatch.setattr(application, "get_settings", lambda: review_settings)
    monkeypatch.setattr(application, "review_db_path", str(tmp_path / "api.db"))

    original = application.process_research
    async def _with_temp_db(job_id: str, data: object, **kw: object) -> None:
        await original(job_id, data, db_path=tmp_path / "api.db", **kw)

    monkeypatch.setattr(application, "process_research", _with_temp_db)

    with TestClient(application.app) as client:
        resp = client.post("/research", json={"company": "Notion"})
        assert resp.status_code == 200, resp.text
        jid = resp.json()["job_id"]

        # 等它停在人工复核，而不是一路跑完或失败
        state: dict = {}
        for _ in range(80):
            state = dict(job_status.get(jid, {}))
            if state.get("status") in ("waiting_review", "completed", "failed"):
                break
            time.sleep(0.1)
        assert state.get("status") == "waiting_review", state
        assert state.get("current_step") == "human_review"
        assert state.get("review_payload", {}).get("company") == "Notion"
        assert not state.get("report"), "中断时绝不能已经成稿"

        # 提交批准决定 → 续跑成稿
        resp = client.post(
            f"/research/{jid}/review",
            json={"approved": True, "rejected_sections": [], "note": "通过"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "completed"

        final = dict(job_status.get(jid, {}))
        assert final["status"] == "completed"
        assert_report_shape(final["report"])


def test_api_review_rejects_on_bad_state(tmp_path: Path, monkeypatch) -> None:
    """review 接口对「已完成 / 不存在的任务」必须明确拒绝，不能静默续跑。"""
    from fastapi.testclient import TestClient

    import application
    from backend.classes.state import job_status

    monkeypatch.setattr(application, "get_settings", lambda: _review_settings())

    with TestClient(application.app) as client:
        # 不存在的任务 → 404
        assert client.post("/research/nope/review", json={"approved": True}).status_code == 404

        # 已完成的任务 → 409（不是 waiting_review，不能重复提交）
        job_status["done-job"] = {
            "status": "completed", "company": "Notion", "thread_id": "tid",
        }
        assert client.post(
            "/research/done-job/review", json={"approved": True}
        ).status_code == 409

        # 还在跑（processing）的任务 → 409，还没到复核点
        job_status["busy-job"] = {
            "status": "processing", "company": "Notion", "thread_id": "tid",
        }
        assert client.post(
            "/research/busy-job/review", json={"approved": True}
        ).status_code == 409

        # 正在复核中（reviewing）→ 409，挡住并发重复提交
        job_status["reviewing-job"] = {
            "status": "reviewing", "company": "Notion", "thread_id": "tid",
        }
        assert client.post(
            "/research/reviewing-job/review", json={"approved": True}
        ).status_code == 409
