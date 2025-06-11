import time
from collections import defaultdict


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, default_requests_per_minute: int = 60, burst_multiplier: int = 1) -> None:
        self.capacity = default_requests_per_minute * burst_multiplier
        self.interval = 60
        self.requests = defaultdict(list)

    async def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.interval
        req_times = [t for t in self.requests[key] if t > window_start]
        self.requests[key] = req_times
        if len(req_times) >= self.capacity:
            return False
        req_times.append(now)
        return True
