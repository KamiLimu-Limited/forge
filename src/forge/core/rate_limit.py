"""In-memory sliding-window rate limiting as a FastAPI dependency.

State is per process; put a shared limiter (e.g. at the reverse proxy) in front
when running multiple workers.
"""

import time
from collections import defaultdict, deque

from fastapi import Request

from forge.core.config import settings
from forge.core.exceptions import TooManyRequests


def client_ip(request: Request) -> str | None:
    if forwarded := request.headers.get("X-Forwarded-For"):
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class RateLimiter:
    def __init__(self, times: int, seconds: int) -> None:
        self.times = times
        self.seconds = seconds
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        key = f"{client_ip(request)}:{request.scope['route'].path}"
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.seconds:
            hits.popleft()
        if len(hits) >= self.times:
            raise TooManyRequests(
                f"Rate limit exceeded: {self.times} requests per {self.seconds}s"
            )
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


auth_rate_limiter = RateLimiter(
    settings.RATE_LIMIT_AUTH_TIMES, settings.RATE_LIMIT_AUTH_SECONDS
)
