"""
Cost guard (tiêu chí 8) — theo dõi chi phí LLM trong Redis.
"""
import time
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_memory_daily_cost: dict[str, float] = {}


def _today_key() -> str:
    return f"cost:daily:{time.strftime('%Y-%m-%d', time.gmtime())}"


def _budget_limit() -> float:
    return min(settings.daily_budget_usd, settings.monthly_budget_usd)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget -> raise HTTPException(status_code=402)."""
    key = _today_key()
    used = 0.0

    if r is not None:
        try:
            val = r.get(key)
            used = float(val) if val is not None else 0.0
        except Exception:
            used = _memory_daily_cost.get(key, 0.0)
    else:
        used = _memory_daily_cost.get(key, 0.0)

    if used >= _budget_limit():
        raise HTTPException(
            status_code=402,
            detail="Daily budget exceeded",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (input_tokens / 1000.0) * PRICE_INPUT_PER_1K + (
        output_tokens / 1000.0
    ) * PRICE_OUTPUT_PER_1K
    key = _today_key()

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(key, cost)
            pipe.expire(key, 86400 * 2)
            pipe.execute()
            return cost
        except Exception:
            pass

    _memory_daily_cost[key] = _memory_daily_cost.get(key, 0.0) + cost
    return cost
