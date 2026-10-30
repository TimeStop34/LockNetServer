from fastapi import Request
from fastapi.responses import JSONResponse
from services.rate_limiter import check_http_rate_limit


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def http_rate_limit_middleware(request: Request, call_next):
    ip = get_client_ip(request)
    if not check_http_rate_limit(ip, request.url.path):
        return JSONResponse(
            {"detail": "Too Many Requests"},
            status_code=429,
        )
    return await call_next(request)