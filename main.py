from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.database import init_db, engine
from core.config import settings, logger
from core.http_middleware import http_rate_limit_middleware
from api.auth import router as auth_router
import api.ws  # noqa: F401 — запускает регистрацию всех WS-обработчиков
from api.jwt_api import router as jwt_router
from api.websocket import router as websocket_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")
    yield
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan)
app.middleware("http")(http_rate_limit_middleware)
app.include_router(auth_router)
app.include_router(websocket_router)
app.include_router(jwt_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        ssl_keyfile=settings.SSL_KEYFILE,
        ssl_certfile=settings.SSL_CERTFILE,
        reload=True,
    )