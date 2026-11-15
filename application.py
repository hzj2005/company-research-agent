import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.llm import DEFAULT_OPENROUTER_MODEL, OPENROUTER_BASE_URL

# S5-B 起：对外入口指向二次开发的新图（原版 backend/graph.py 保留作 upstream 对照）
from capabilities.briefing import briefing_backend_scope
from capabilities.retrieval import make_document_tool
from config.loader import build_thread_id, get_settings, resolve_postgres_dsn
from graph.builder import build_graph
from graph.state import initial_state
from persistence.checkpointer import CheckpointSession
from persistence.job_store import PostgresJobStore
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """按 JOB_STORE 决定台账落库还是落内存；退出时关池子，别把连接挂在那。"""
    global job_store
    settings = get_settings()
    if settings.app.job_store == "postgres":
        try:
            job_store = await PostgresJobStore(resolve_postgres_dsn(settings)).open()
            logger.info("任务台账：Postgres（重启后仍可查）")
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
    company: str
    company_url: str | None = None
    industry: str | None = None
    hq_location: str | None = None
    tavily_api_key: str | None = None
    openrouter_api_key: str | None = None
    model: str | None = None

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

        # Create the job before starting the background task. The SSE endpoint
        # begins polling immediately after this response; without this entry it
        # can time out while initial research work is still running.
        job_status[job_id].update({
            "status": "pending",
            "company": data.company,
            "last_update": datetime.now().isoformat(),
        })
        if job_store is not None:
            # 先落库再排队：前端立刻查 /research/{id} 就能看到 pending
            await job_store.create_job(
                job_id, data.model_dump(exclude={"tavily_api_key", "openrouter_api_key"})
            )
        asyncio.create_task(process_research(job_id, data))

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

async def process_research(job_id: str, data: ResearchRequest, db_path=None):
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
        # job_id 保证并发请求各有独立 checkpoint 线程，不互相覆盖
        thread_id = build_thread_id(f"{data.company}:{job_id}", settings=settings)

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

            snapshot = await compiled.aget_state(config)
            final_state = dict(snapshot.values)

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
                await job_store.update_job(job_id, status="completed")
                await job_store.store_report(job_id, report_content)
            
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
            await job_store.update_job(job_id, status="failed", error=str(e))

@app.get("/")
async def ping():
    return {"message": "Alive"}

@app.get("/config")
async def get_config():
    """Report which LLM credentials the server already has, without exposing them."""
    return {
        "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
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

@app.get("/research/{job_id}")
async def get_research(job_id: str):
    """台账查询：配了 Postgres 就能跨重启查，否则退回进程内字典。

    注意 SSE 那条流仍然只认内存（`job_status`），所以多 worker 部署时这里能查到、
    流的进度可能对不上——这是 S12 明确留下的边界，没假装解决。
    """
    if job_store is not None:
        job = await job_store.get_job(job_id)
    else:
        job = job_status.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Research job not found")
    return job

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
    return report

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
