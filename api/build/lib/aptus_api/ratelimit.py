"""In-process sliding-window rate limiting.

Deliberately has no external store. A shared limiter would mean Redis,
and a mandatory Redis breaks the dependency-free single-node appliance
a small RTO has to be able to run. The trade-off is explicit: across
several API processes each holds its own counter, so the effective
limit multiplies by the process count. Acceptable at single-node scale,
and the limitation is recorded rather than quietly tolerated.
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limits: dict):
        self._limits = limits
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, bucket: str, identity: str, now: float | None = None) -> tuple[bool, int]:
        """Record an attempt. Returns (allowed, retry_after_seconds)."""
        limit = self._limits.get(bucket)
        if limit is None:
            return True, 0
        max_hits, window = limit
        now = time.monotonic() if now is None else now
        key = (bucket, identity)

        with self._lock:
            hits = self._hits[key]
            cutoff = now - window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= max_hits:
                return False, max(1, int(hits[0] + window - now) + 1)
            hits.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
