"""
Production AI Agent — Part 6 Final Project
"""
import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Format mỗi dòng log thành 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            payload.update(record.extra_fields)
        return json.dumps(payload, ensure_ascii=False)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
root_logger = logging.getLogger()
root_logger.handlers = [handler]
root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

logger = logging.getLogger("agent")

_is_ready = False
_in_flight = 0


def log_json(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"extra_fields": {"event": event, **fields}})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý lifecycle startup và graceful shutdown (SIGTERM)."""
    global _is_ready
    _is_ready = True
    log_json("startup", environment=settings.environment, port=settings.port)
    yield
    _is_ready = False
    log_json("shutdown_started", in_flight=_in_flight)
    deadline = time.time() + 10.0
    while _in_flight > 0 and time.time() < deadline:
        await asyncio.sleep(0.05)
    if r is not None:
        try:
            r.close()
        except Exception:
            pass
    log_json("shutdown_complete")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def track_and_log_requests(request: Request, call_next):
    global _in_flight
    _in_flight += 1
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        _in_flight -= 1
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        log_json(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            ms=elapsed_ms,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log_json("unhandled_error", level=logging.ERROR, path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = None


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn chạy."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness probe: 200 khi sẵn sàng, 503 khi Redis không kết nối được."""
    if _is_ready and redis_healthy():
        return {"status": "ready", "redis": "ok"}
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "redis": "unavailable"},
    )


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Endpoint chính: xác thực API key -> rate limit -> cost guard -> mock LLM."""
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost_usd = record_cost(input_tokens, output_tokens)

    log_json(
        "ask_completed",
        user_id=body.user_id or "anonymous",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost_usd, 6),
    )
    return {"question": body.question, "answer": answer}
