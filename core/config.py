import logging
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # БД
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "lnetsvr"
    DB_PASSWORD: str = ""
    DB_NAME: str = "lkmaindb"

    # JWT и пространство
    JWT_SECRET_KEY_BASE64: str
    SPACE: str

    # SSL-сертификаты (по умолчанию лежат в res/)
    SSL_KEYFILE: str = "res/key.pem"
    SSL_CERTFILE: str = "res/cert.pem"

    # Messages
    MESSAGE_EDIT_WINDOW_HOURS: int = 24
    MESSAGE_MAX_BYTES: int = 65536
    MESSAGE_RATE_LIMIT_PER_MINUTE: int = 30

    class Config:
        env_file = os.getenv("ENV_FILE", "res/server.env")
        env_file_encoding = "utf-8"

settings = Settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)