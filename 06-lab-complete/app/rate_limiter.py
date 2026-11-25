"""
Rate limiting (tiêu chí 7) — sliding window 60s lưu trong Redis.
"""
import time
import uuid
from collections import defaultdict
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60
_memory_windows: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(key: str) -> None:
    """Kiểm tra giới hạn request/phút theo API key; vượt -> HTTP 429."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS

    if r is not None:
        try:
            redis_key = f"ratelimit:{key}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, count = pipe.execute()

            if count >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(WINDOW_SECONDS)},
                )

            member = f"{now}:{uuid.uuid4().hex}"
            pipe = r.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            pipe.execute()
            return
        except HTTPException:
            raise
        except Exception:
            pass

    # Fallback in-memory khi chạy local không có REDIS_URL
    timestamps = [t for t in _memory_windows[key] if t > window_start]
    if len(timestamps) >= limit:
        _memory_windows[key] = timestamps
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
    timestamps.append(now)
    _memory_windows[key] = timestamps
