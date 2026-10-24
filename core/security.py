import base64
import hashlib
import time
import uuid
from datetime import datetime, timezone
import bcrypt
import jwt
from .config import settings

JWT_SECRET = base64.b64decode(settings.JWT_SECRET_KEY_BASE64)

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def generate_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def create_jwt_pair(user_id: int, space: str) -> dict:
    iat = int(time.time())
    jti = uuid.uuid4().hex   # <-- гарантирует уникальность токена

    access_payload = {
        "sub": str(user_id),
        "space": space,
        "iat": iat,
        "exp": iat + 3600,
        "type": "access",
        "jti": jti + "-a",
    }
    refresh_payload = {
        "sub": str(user_id),
        "space": space,
        "iat": iat,
        "exp": iat + 3600 * 24 * 30,
        "type": "refresh",
        "jti": jti + "-r",
    }

    access_token = jwt.encode(access_payload, JWT_SECRET, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, JWT_SECRET, algorithm="HS256")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "access_hash": generate_token_hash(access_token),
        "refresh_hash": generate_token_hash(refresh_token),
        "refresh_expires_at": datetime.fromtimestamp(iat + 3600 * 24 * 30, tz=timezone.utc),
        "expires_in": 3600,
    }

def decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])