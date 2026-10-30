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
http_rate_limiter = RateLimiter()


# Готовые профили для HTTP-эндпоинтов
HTTP_LIMITS = {
    "/api/v1/jwt/kcheck": (5, 60),      # 5 запросов / минуту на IP
    "/api/v1/auth/login": (5, 60),
    "/api/v1/auth/register": (5, 3600), # 5 регистраций / час на IP
}


def check_http_rate_limit(ip: str, path: str) -> bool:
    cfg = HTTP_LIMITS.get(path)
    if cfg is None:
        return True
    limit, window = cfg
    return http_rate_limiter.check(f"http:{path}:{ip}", limit, window)