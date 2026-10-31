"""In-memory rate limiter to protect public lookup and sensitive endpoints."""
from collections import defaultdict
from datetime import datetime, timedelta
import threading

from fastapi import Request

from app.core.errors import AppError


class RateLimiter:
    def __init__(self, max_requests: int = 15, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests: dict[str, list[datetime]] = defaultdict(list)
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = datetime.utcnow()
        cutoff = now - self.window
        with self.lock:
            history = [t for t in self.requests[key] if t > cutoff]
            if len(history) >= self.max_requests:
                raise AppError(429, "Too many status lookup attempts. Please wait a moment before trying again.")
            history.append(now)
            self.requests[key] = history

    def record_failure(self, key: str, max_failures: int = 8, penalty_seconds: int = 300) -> None:
        pass


_lookup_limiter = RateLimiter(max_requests=15, window_seconds=60)
lookup_limiter = _lookup_limiter


def rate_limit_lookup(request: Request) -> None:
    client_ip = request.client.host if request.client else "127.0.0.1"
    # Also include X-Forwarded-For if available
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    _lookup_limiter.check(client_ip)
