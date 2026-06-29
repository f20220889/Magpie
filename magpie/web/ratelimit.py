"""Tiny in-memory rate limiter for auth endpoints (brute-force defense).

A per-key sliding window of recent hit timestamps. Keyed by client IP so a
single host can't hammer login/signup. State is process-local: it resets on
restart and is not shared across workers — fine for a single-process local app.
For a multi-worker deployment, back this with Redis (or run one auth worker).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, max_hits: int, window_seconds: int) -> None:
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Record a hit for ``key``; raise 429 if it exceeds the window budget."""
        now = time.monotonic()
        cutoff = now - self.window
        dq = self._hits[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self.max_hits:
            retry = int(dq[0] + self.window - now) + 1
            raise HTTPException(
                status_code=429,
                detail="too many attempts, try again later",
                headers={"Retry-After": str(retry)},
            )
        dq.append(now)


def client_ip(request: Request) -> str:
    """Best-effort client IP. Behind a trusted proxy, parse X-Forwarded-For."""
    return request.client.host if request.client else "unknown"
