from collections import defaultdict, deque
from time import time


class RateLimiter:
    def __init__(self):
        self._buckets: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window_sec: int = 60) -> bool:
        now = time()
        bucket = self._buckets[key]
        while bucket and bucket[0] < now - window_sec:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


message_rate_limiter = RateLimiter()