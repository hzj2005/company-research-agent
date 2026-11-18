import asyncio
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

# Windows 默认的 ProactorEventLoop 不支持 psycopg 的 async 模式，配了
# POSTGRES_DSN 时连接池会一直失败、服务卡在 startup（2026-11-18 实测）。
# 必须在任何事件循环创建之前设置，所以放在模块最顶部、uvicorn 之前。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from langgraph.types import Command

from backend.llm import DEFAULT_OPENROUTER_MODEL, OPENROUTER_BASE_URL

# S5-B 起：对外入口指向二次开发的新图（原版 backend/graph.py 保留作 upstream 对照）
from capabilities.briefing import briefing_backend_scope
from capabilities.retrieval import make_document_tool
from config.loader import build_thread_id, get_settings, resolve_postgres_dsn
from graph.builder import build_graph
from graph.state import initial_state
from persistence.checkpointer import CheckpointSession
from persistence.job_store import PostgresJobStore, missing_tables
from backend.services.pdf_service import PDFService
from backend.classes.state import EventQueue, job_status

# Load environment variables from .env file at startup.
# override=False：**显式环境变量优先于 .env**。否则测试/CI 想临时指定
# JOB_STORE=memory 会把 .env 里的 postgres 覆盖回来，测试直接写进真实库。
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=False)

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
logger.addHandler(console_handler)

# S12.2：任务台账后端。None = 用进程内 job_status（测试/离线默认）。
job_store: PostgresJobStore | None = None

# HITL review 续跑用的 checkpoint 路径注入点。默认 None = 走 settings 配置
# （sqlite 落到 data/checkpoints.db 或 postgres）；测试用它把存档钉在临时目录，
# 与 process_research 的 db_path 对称，避免污染项目 data/。
review_db_path: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """按 JOB_STORE 决定台账落库还是落内存；退出时关池子，别把连接挂在那。"""
    global job_store
    settings = get_settings()
    if settings.app.job_store == "postgres":
        try:
            job_store = await PostgresJobStore(resolve_postgres_dsn(settings)).open()
            missing = await missing_tables(job_store)
            if missing:
                # 表没建：现在抛，比等第一个请求 500 强，而且提示能直接照做
                raise RuntimeError(
                    f"Postgres 缺少台账表 {missing}；先跑 "
                    "`uv run python -m persistence.setup_postgres`"
                )
            logger.info("任务台账：Postgres（重启后仍可查）")
            try:
                # 上一个进程留下的非终态任务永远不会有人推进（job_status 在内存里），
                # 启动时收尾一次，否则历史列表里会一直挂着 pending。
                cleaned = await job_store.interrupt_stale(
                    "进程重启，任务未完成（启动时自动收尾）"
                )
                if cleaned:
                    logger.warning("收尾了 %s 条上次进程留下的未完成任务", cleaned)
            except Exception as exc:  # 收尾失败不该拦住启动
                logger.warning("收尾未完成任务失败：%s", exc)
        except Exception as exc:  # 连不上 / 库没建 / DSN 空
            if settings.app.mode == "live":
                # 真实模式必须失败：宁可起不来，也不要假装存下来了
                raise
            logger.warning(
                "JOB_STORE=postgres 但台账库不可用（%s）；fixture 模式退回进程内内存。"
                " 排查：docker compose -f docker-compose.postgres.yml ps / "
                "uv run python -m persistence.setup_postgres",
                exc,
            )
            job_store = None
    else:
        logger.info("任务台账：进程内内存（默认；设 JOB_STORE=postgres 可落库）")
    try:
        yield
    finally:
        if job_store is not None:
            await job_store.close()
            job_store = None


app = FastAPI(title="Tavily Company Research API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
pdf_service = PDFService({"pdf_output_dir": "pdfs"})

# 上游的 MongoDB 台账层已在 S12.2 换成 Postgres（见 persistence/job_store.py）。
# backend/services/mongodb.py 保留作上游对照，但这里不再实例化：多一个可选依赖
# 就多一条「本地能跑、换台机器跑不起来」的路。

class ResearchRequest(BaseModel):
    """公司名是**唯一**被图消费的字段。

    下面几个可选字段只为兼容上游客户端而保留声明，图一个都不读：检索与模型的
    凭据只从环境变量取（`/config` 也印证这一点），把 key 放进请求体既不会被用，
    还会被写进日志的风险。写进台账的也只有 `company`。
    """

    company: str = Field(min_length=1)
    company_url: str | None = None
    industry: str | None = None
    hq_location: str | None = None
    tavily_api_key: str | None = None
    openrouter_api_key: str | None = None
    model: str | None = None

    @field_validator("company")
    @classmethod
    def _require_real_company(cls, value: str) -> str:
        """公司名是唯一被图消费的字段，空白串必须挡在门外。

        不挡的话 `{"company": ""}` 会 200 并真的跑一次空调研——
        既浪费一次运行，又在台账里留一条没有意义的记录。
        """
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("company 不能为空")
        return cleaned

class PDFGenerationRequest(BaseModel):
    report_content: str
    company_name: str | None = None

@app.options("/research")
async def preflight():
    response = JSONResponse(content=None, status_code=200)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@app.post("/research")
async def research(data: ResearchRequest):
    try:
        logger.info(f"Received research request for {data.company}")
        job_id = str(uuid.uuid4())

        # HITL 的恢复前提：thread_id 必须在任务结束后仍可查。它和 job_id 一一对应，
        # 这里先算好放进台账 inputs，`POST /research/{id}/review` 就能取回续跑。
        settings = get_settings()
        thread_id = build_thread_id(f"{data.company}:{job_id}", settings=settings)

        # Create the job before starting the background task. The SSE endpoint
        # begins polling immediately after this response; without this entry it
        # can time out while initial research work is still running.
        job_status[job_id].update({
            "status": "pending",
            "company": data.company,
            "thread_id": thread_id,
            "last_update": datetime.now().isoformat(),
        })
        if job_store is not None:
            # 先落库再排队：前端立刻查 /research/{id} 就能看到 pending。
            # 落库失败就把内存里那条也撤掉——否则库和内存各说一套。
            try:
                payload = data.model_dump(exclude={"tavily_api_key", "openrouter_api_key"})
                payload["thread_id"] = thread_id
                await job_store.create_job(job_id, payload)
            except Exception:
                job_status.pop(job_id, None)
                raise
        asyncio.create_task(process_research(job_id, data, thread_id=thread_id))

        response = JSONResponse(content={
            "status": "accepted",
            "job_id": job_id,
            "message": "Research started. Connect to /research/{job_id}/stream for updates."
        })
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    except Exception as e:
        logger.error(f"Error initiating research: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def process_research(job_id: str, data: ResearchRequest, db_path=None, thread_id: str | None = None):
    """Process research request asynchronously and store results.

    S5-B：用新图（7 节点 + research 子图）替代原版线性 DAG。
    `db_path` 仅作测试注入点，让端到端用例落在临时 SQLite 而不污染项目 data/。

    如实边界：新图当前只消费 `company`；上游的 `company_url / industry /
    hq_location / model / 请求体里的 api_key` 均**不消费**。检索与模型凭据只从
    环境变量解析（见 config/loader.py），不接收请求体传 key，避免密钥进日志。
    """
    try:
        await asyncio.sleep(0.5)  # Brief delay (kept from upstream for SSE startup)

        logger.info(f"Starting research for {data.company}")
        settings = get_settings()
        # job_id 保证并发请求各有独立 checkpoint 线程，不互相覆盖。
        # 调用方（research()）会提前算好并落库，这里复用以保证续跑拿到同一个 thread。
        if thread_id is None:
            thread_id = build_thread_id(f"{data.company}:{job_id}", settings=settings)
        # 内存台账也要能取回 thread_id，否则 JOB_STORE=memory 时 review 接口没法续跑
        job_status[job_id]["thread_id"] = thread_id

        # 简报后端的 httpx client 归本次请求所有：长驻服务里不关会每请求泄漏一个
        async with (
            briefing_backend_scope(settings) as backend,
            CheckpointSession(settings=settings, path=db_path) as session,
        ):
            compiled = session.compile(
                build_graph(settings, make_document_tool(settings), briefing_backend=backend)
            )
            config = session.config_for(thread_id)

            # astream(updates) 产出 {节点名: {字段: 值}}，直接映射为 current_step
            async for event in compiled.astream(
                initial_state(data.company), config=config, stream_mode="updates"
            ):
                node_name = next(iter(event), 'unknown') if event else 'unknown'
                logger.debug(f"Node completed: {node_name}")
                job_status[job_id].update({
                    "status": "processing",
                    "current_step": node_name,
                    "last_update": datetime.now().isoformat()
                })
                if job_store is not None:
                    # 之前这里只写内存：库里 current_step 永远是空的，接口却把它返回出去。
                    # 台账写失败只告警，绝不因为「记进度」把调研本身搞挂。
                    try:
                        await job_store.update_job(
                            job_id, status="processing", current_step=node_name
                        )
                    except Exception as exc:
                        logger.warning("进度写台账失败（调研继续）：%s", exc)

            snapshot = await compiled.aget_state(config)
            final_state = dict(snapshot.values)

            # S13 HITL：图停在 interrupt() 时没有 report，snapshot.tasks 里带 interrupts。
            # 不能像以前那样直接判 failed——要转成「待人工复核」，把 payload 存起来等人提交。
            interrupts = [
                item.value
                for task in (snapshot.tasks or ())
                for item in (getattr(task, "interrupts", None) or ())
            ]
            if interrupts and not final_state.get("report"):
                payload = interrupts[0]
                job_status[job_id].update({
                    "status": "waiting_review",
                    "current_step": "human_review",
                    "review_payload": payload,
                    "last_update": datetime.now().isoformat(),
                })
                if job_store is not None:
                    try:
                        # 落库 review_payload：只放内存的话，用户刷新页面就看不到待审证据了
                        # （SSE 事件是一次性的，刷新即丢）。
                        await job_store.update_job(
                            job_id,
                            status="waiting_review",
                            current_step="human_review",
                            review_payload=payload,
                        )
                    except Exception as exc:
                        logger.warning("复核状态写台账失败（调研继续）：%s", exc)
                logger.info(f"Research paused for human review: {data.company}")
                return

        report_content = final_state.get('report')
        
        if report_content:
            logger.info(f"Research completed. Report length: {len(report_content)}")
            
            job_status[job_id].update({
                "status": "completed",
                "report": report_content,
                "company": data.company,
                "last_update": datetime.now().isoformat()
            })
            
            if job_store is not None:
                # 先存正文再改状态：反过来的话，store_report 失败会留下
                # 「状态 completed 但查不到报告」的假成功。
                await job_store.store_report(job_id, report_content)
                # 证据原文也一并存下来：下次搜同一个公司时，要能展示「上次查到了什么」，
                # 光有报告正文不够——结论从哪来要看原文。
                try:
                    curated = final_state.get("curated_data") or {}
                    if curated:
                        saved = await job_store.store_evidence(job_id, curated)
                        logger.info("已保存 %d 条证据原文", saved)
                except Exception as exc:
                    # 证据存失败不该让整次调研算失败：报告已经成了。
                    logger.warning("证据原文写台账失败（报告已成稿）：%s", exc)
                await job_store.update_job(job_id, status="completed")
            
            logger.info(f"Research completed successfully for {data.company}")
        else:
            logger.error(f"Research completed without report. State keys: {list(final_state.keys())}")
            job_status[job_id].update({
                "status": "failed",
                "error": "No report generated",
                "last_update": datetime.now().isoformat()
            })
            if job_store is not None:
                await job_store.update_job(job_id, status="failed", error="No report generated")

    except Exception as e:
        logger.error(f"Research failed: {str(e)}", exc_info=True)
        job_status[job_id].update({
            "status": "failed",
            "error": str(e),
            "last_update": datetime.now().isoformat()
        })
        
        if job_store is not None:
            # 台账写失败不能再抛：那会把真正的失败原因盖掉，改成记日志
            try:
                await job_store.update_job(job_id, status="failed", error=str(e))
            except Exception:
                logger.exception("台账写入失败（job %s）；原始错误见上一条日志", job_id)

@app.get("/")
async def ping():
    return {"message": "Alive"}

@app.get("/health")
@app.get("/api/health")
async def health():
    """存活探针。

    `/api/health` 是别名：外部监控和预览面板默认探这个路径，没有就会每几秒
    刷一条 404（实测日志里刷了几十条）。两个路径都指同一个函数，不额外开销。
    """
    return {"status": "ok"}

@app.get("/config")
async def get_config():
    """Report which LLM credentials the server already has, without exposing them.

    `app_mode` / `requires_llm_key` 是给前端判断「要不要卡住提交」用的：
    fixture 模式跑的是本地固定语料 + 确定性 stub，**不需要任何 key**；
    上游前端不知道这件事，没 key 就直接弹设置框、不提交（实测就是这么被挡住的）。
    """
    settings = get_settings()
    mode = settings.app.mode
    return {
        "app_mode": mode,
        "requires_llm_key": mode == "live",
        "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        # 本项目 live 模式实际用的是 DashScope（qwen-plus），不报它前端会误判「没配 key」
        "dashscope_configured": bool(os.getenv("DASHSCOPE_API_KEY")),
        "tavily_configured": bool(os.getenv("TAVILY_API_KEY")),
        "default_model": os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL,
    }

_models_cache: dict = {"fetched_at": 0.0, "models": []}
MODELS_CACHE_TTL = 3600

def _per_million(price: str | None) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    return round(value * 1_000_000, 4) if value >= 0 else None

@app.get("/models")
async def list_models():
    """List text-generation models available on OpenRouter (cached)."""
    if _models_cache["models"] and time.time() - _models_cache["fetched_at"] < MODELS_CACHE_TTL:
        return {"models": _models_cache["models"]}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{OPENROUTER_BASE_URL}/models")
            response.raise_for_status()
            raw_models = response.json().get("data", [])
    except Exception as e:
        logger.warning(f"Failed to fetch OpenRouter models: {e}")
        if _models_cache["models"]:
            return {"models": _models_cache["models"]}
        raise HTTPException(status_code=502, detail="Could not load models from OpenRouter")

    models = []
    for m in raw_models:
        model_id = m.get("id", "")
        output_modalities = (m.get("architecture") or {}).get("output_modalities") or ["text"]
        prompt_price = _per_million((m.get("pricing") or {}).get("prompt"))
        if model_id.endswith(":batch") or "text" not in output_modalities or prompt_price is None:
            continue
        name = m.get("name") or model_id
        models.append({
            "id": model_id,
            "name": name.split(": ", 1)[-1],
            "provider": model_id.lstrip("~").split("/", 1)[0],
            "context_length": m.get("context_length"),
            "prompt_price": prompt_price,
            "completion_price": _per_million((m.get("pricing") or {}).get("completion")),
            "created": m.get("created", 0),
        })
    models.sort(key=lambda model: model["created"], reverse=True)

    _models_cache.update(fetched_at=time.time(), models=models)
    return {"models": models}

@app.get("/research/pdf/{filename}")
async def get_pdf(filename: str):
    pdf_path = os.path.join("pdfs", filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(pdf_path, media_type='application/pdf', filename=filename)

@app.get("/research")
async def list_research(limit: int = 20, company: str | None = None):
    """历史任务列表（最近 N 条），可按公司模糊筛选。

    没有这个入口时，历史只存在于库里：知道 job_id 才能查，等于看不见。
    `has_report` / `report_chars` 让人一眼分清「跑完了有报告」和「只有一条状态」。
    """
    limit = max(1, min(limit, 100))
    if job_store is not None:
        return {"source": "postgres", "jobs": await job_store.list_jobs(limit=limit, company=company)}

    rows = []
    for job_id, item in job_status.items():
        name = str(item.get("company") or "")
        if company and company.strip().lower() not in name.lower():
            continue
        report = item.get("report") or ""
        rows.append({
            "job_id": job_id,
            "company": name,
            "status": item.get("status"),
            "current_step": item.get("current_step"),
            "error": item.get("error"),
            "created_at": item.get("last_update"),
            "has_report": bool(report),
            "report_chars": len(report),
        })
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return {"source": "memory", "jobs": rows[:limit]}


@app.get("/research/history")
async def research_history(company: str, limit: int = 5, include_evidence: bool = True):
    """查某家公司之前查过的结果（模糊匹配），供前端「先看历史、要不要重新查」用。

    公司名用 ilike 模糊匹配：搜 `Meta` 能命中 `Meta Platforms`、`Meta Platforms, Inc.`，
    搜 `英伟达` 也能命中 `Nvidia`。每条历史带报告正文和证据条数；带
    `include_evidence=true` 时连证据原文一起返回，省得前端再逐条查。

    只返回**有报告**的记录：没跑完的任务不算「历史结果」。
    """
    company = company.strip()
    if not company:
        raise HTTPException(status_code=400, detail="company 不能为空")

    if job_store is None:
        # 没有落库台账时只剩进程内字典，重启即失。照实返回空，不假装有历史。
        return {"source": "memory", "company": company, "matches": []}

    matches = await job_store.find_history(company, limit=limit)
    if include_evidence:
        for item in matches:
            item["evidence"] = await job_store.get_evidence(item["job_id"])
    return {"source": "postgres", "company": company, "matches": matches}


@app.get("/research/{job_id}")
async def get_research(job_id: str):
    """台账查询：配了 Postgres 就能跨重启查，否则退回进程内字典。

    注意 SSE 那条流仍然只认内存（`job_status`），所以多 worker 部署时这里能查到、
    流的进度可能对不上——这是 S12 明确留下的边界，没假装解决。

    HITL 待复核时这里会带上 `review_payload`（证据摘要）：前端刷新页面后靠它
    恢复审批面板，不用重新跑一遍调研。
    """
    if job_store is not None:
        job = await job_store.get_job(job_id)
        if job and job.get("status") == "waiting_review" and not job.get("review_payload"):
            # 台账里没有但内存里有（老数据或台账写失败）：内存这份更全，补上
            fallback = job_status.get(job_id) or {}
            job = {**job, "review_payload": fallback.get("review_payload")}
    else:
        job = job_status.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")
    return job

class ReviewRequest(BaseModel):
    """HITL 成稿前人工复核的决策。

    `rejected_sections` 只能填 `settings.yaml` 里注册的栏目，图内 `human_review`
    节点会再做一次白名单过滤（`_normalize_decision`），非法栏目一律丢弃、按
    fail-safe 处理，所以这里不重复校验，只保证类型正确。
    """
    approved: bool = Field(default=True)
    rejected_sections: list[str] = Field(default_factory=list)
    note: str = Field(default="")

@app.post("/research/{job_id}/review")
async def review_research(job_id: str, data: ReviewRequest):
    """把人的复核决定送回图里，从磁盘 checkpoint 续跑。

    流程：取回 thread_id → 新建 CheckpointSession → `Command(resume=decision)`
    续跑 → 结果写回 `jobs` / `reports`。CLI（graph/run.py）已经证明「新进程恢复」
    可行，这里只是把触发方式从命令行换成 HTTP。

    只有停在 `waiting_review` 的任务才接受这个调用；已完成的直接 409，避免重复提交。
    """
    # 取 thread_id：优先台账（跨重启），退回内存（单 worker / 测试）
    thread_id: str | None = None
    if job_store is not None:
        job = await job_store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Research job not found")
        thread_id = (job.get("inputs") or {}).get("thread_id")
    else:
        job = job_status.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Research job not found")
        thread_id = job.get("thread_id")

    if not thread_id:
        raise HTTPException(status_code=409, detail="该任务没有可恢复的 checkpoint")

    # 只有停在 waiting_review 的任务才接受复核：completed/failed 是终态，pending/processing
    # 还没跑到复核点，续跑会拿到错误的 checkpoint 快照。
    if job.get("status") != "waiting_review":
        raise HTTPException(
            status_code=409,
            detail=f"任务当前状态为 {job.get('status')}，只有 waiting_review 才能提交复核",
        )

    decision = data.model_dump()
    logger.info(f"Resuming {job_id} with review decision: approved={decision['approved']}")

    # 先占位成 reviewing：同一任务的第二次复核请求必须被挡住。
    # 续跑是同步的（可能好几秒），这期间状态不是 waiting_review，
    # 并发进来的第二个请求会拿到 409，而不是重复续跑一遍。
    job_status[job_id]["status"] = "reviewing"
    if job_store is not None:
        try:
            await job_store.update_job(job_id, status="reviewing", current_step="human_review")
        except Exception as exc:
            logger.warning("复核中状态写台账失败（继续复核）：%s", exc)

    # 续跑结果写回台账，复用 process_research 里那套「先正文后状态」的落库逻辑
    async def _run_and_persist():
        settings = get_settings()
        async with (
            briefing_backend_scope(settings) as backend,
            CheckpointSession(settings=settings, path=review_db_path) as session,
        ):
            compiled = session.compile(
                build_graph(settings, make_document_tool(settings), briefing_backend=backend)
            )
            config = session.config_for(thread_id)
            async for _event in compiled.astream(
                Command(resume=decision), config=config, stream_mode="updates"
            ):
                pass
            snapshot = await compiled.aget_state(config)
            return dict(snapshot.values)

    try:
        final_state = await asyncio.create_task(_run_and_persist())
    except Exception as e:
        logger.error(f"Review resume failed for {job_id}: {str(e)}", exc_info=True)
        if job_store is not None:
            await job_store.update_job(job_id, status="failed", error=str(e))
        job_status[job_id].update({"status": "failed", "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))

    report_content = final_state.get("report")
    if not report_content:
        # 理论上恢复后必然成稿；留个兜底，别让「状态 completed 但查不到报告」出现
        err = "No report generated after review"
        if job_store is not None:
            try:
                await job_store.update_job(job_id, status="failed", error=err)
            except Exception:
                logger.warning("复核失败状态写台账失败（job %s）", job_id)
        job_status[job_id].update({"status": "failed", "error": err})
        raise HTTPException(status_code=500, detail=err)

    job_status[job_id].update({
        "status": "completed",
        "report": report_content,
        "company": job.get("company"),
        "last_update": datetime.now().isoformat(),
    })
    if job_store is not None:
        # 台账写失败只记日志：报告**已经成稿**（内存里有、SSE 也能拿到），
        # 让它变成 500 会让前端显示「提交复核失败」，用户以为没成稿而重复提交，
        # 实际上任务早已 completed、再次提交只会拿到 409。
        try:
            await job_store.store_report(job_id, report_content)
            await job_store.update_job(job_id, status="completed")
        except Exception as exc:
            logger.warning("复核结果写台账失败（报告已成稿，job %s）：%s", job_id, exc)
    return {"status": "completed", "job_id": job_id, "report": report_content}



@app.get("/research/{job_id}/stream")
async def stream_research(job_id: str):
    """Stream research progress via SSE"""
    async def event_generator():
        try:
            # Wait for job to exist
            for _ in range(50):
                if job_id in job_status:
                    break
                await asyncio.sleep(0.1)
            
            last_step = None
            
            # Stream status updates
            while job_id in job_status:
                result = job_status[job_id]
                status = result.get("status")
                current_step = result.get("current_step")
                events = result.get("events", [])
                
                # Send node progress updates when step changes
                if status == "processing" and current_step and current_step != last_step:
                    data = json.dumps({"type": "progress", "step": current_step})
                    yield f"data: {data}\n\n"
                    last_step = current_step
                
                # Send all queued events (FIFO - pop from start)
                while events:
                    event = events.pop(0)
                    data = json.dumps(event)
                    yield f"data: {data}\n\n"
                
                if status == "completed" and (report := result.get("report")):
                    data = json.dumps({"type": "complete", "report": report})
                    yield f"data: {data}\n\n"
                    break
                elif status == "failed":
                    data = json.dumps({"type": "error", "error": result.get("error", "Unknown error")})
                    yield f"data: {data}\n\n"
                    break
                elif status == "waiting_review":
                    # HITL：通知前端弹出复核面板，并附上决策所需字段
                    data = json.dumps({
                        "type": "review_required",
                        "payload": result.get("review_payload"),
                    })
                    yield f"data: {data}\n\n"
                    break
                
                # Wake immediately on new events; the timeout catches status changes
                if isinstance(events, EventQueue):
                    await events.wait(timeout=0.1)
                else:
                    await asyncio.sleep(0.1)
        except Exception as e:
            data = json.dumps({"type": "error", "error": str(e)})
            yield f"data: {data}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/research/{job_id}/report")
async def get_research_report(job_id: str):
    """报告优先从台账拿（能跨重启），拿不到再看内存，最后才说 404。"""
    if job_store is not None:
        report = await job_store.get_report(job_id)
        if report:
            return report
        job = await job_store.get_job(job_id)
        if job:
            return JSONResponse(
                status_code=202,
                content={"status": job.get("status", "pending"), "message": "Report not ready yet"}
            )
        raise HTTPException(status_code=404, detail="Job not found")

    if job_id in job_status:
        result = job_status[job_id]
        if report := result.get("report"):
            return {"report": report}
        # Job exists but report not ready yet
        return JSONResponse(
            status_code=202,
            content={"status": result.get("status", "pending"), "message": "Report not ready yet"}
        )
    raise HTTPException(status_code=404, detail="Job not found")

@app.post("/generate-pdf")
async def generate_pdf(data: PDFGenerationRequest):
    """Generate a PDF from markdown content and stream it to the client."""
    try:
        success, result = pdf_service.generate_pdf_stream(data.report_content, data.company_name)
        if success:
            pdf_buffer, filename = result
            return StreamingResponse(
                pdf_buffer,
                media_type='application/pdf',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"'
                }
            )
        else:
            raise HTTPException(status_code=500, detail=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
