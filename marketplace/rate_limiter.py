"""
Per-user and per-IP sliding window rate limiter (in-memory).
"""

import time
import threading


class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> dict:
        """Check if key (user_id or IP) is within rate limit.
        Returns {allowed: bool, retry_after: int}.
        """
        now = time.time()

        with self._lock:
            timestamps = self._timestamps.get(key, [])
            # Keep only timestamps within the window
            timestamps = [t for t in timestamps if now - t < self.window_seconds]

            if len(timestamps) >= self.max_requests:
                oldest = timestamps[0]
                retry_after = int(self.window_seconds - (now - oldest)) + 1
                self._timestamps[key] = timestamps
                return {"allowed": False, "retry_after": retry_after}

            timestamps.append(now)
            self._timestamps[key] = timestamps
            return {"allowed": True, "retry_after": 0}

    def cleanup(self):
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            for key in list(self._timestamps.keys()):
                self._timestamps[key] = [
                    t for t in self._timestamps[key]
                    if now - t < self.window_seconds
                ]
                if not self._timestamps[key]:
                    del self._timestamps[key]


# Chat endpoint: 10 requests/min per user
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Auth endpoints: 5 requests/min per IP (blocks brute force + credit farming)
auth_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)

# Signup: 3 accounts/min per IP (blocks credit farming)
signup_rate_limiter = RateLimiter(max_requests=3, window_seconds=60)
