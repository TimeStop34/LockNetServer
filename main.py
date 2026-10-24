from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.database import init_db, engine
from core.config import settings, logger
from api.auth import router as auth_router
from api.ws import *
from api.jwt_api import router as jwt_router
from api.websocket import router as ws_router
from services.connection_manager import manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация БД (создание таблиц)
    await init_db()
    logger.info("Database initialized")
    yield
    await engine.dispose()
    logger.info("Shutdown complete")

app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.include_router(ws_router)
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