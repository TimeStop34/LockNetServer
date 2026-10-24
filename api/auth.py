from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from models.schemas import RegisterRequest, LoginRequest, RefreshRequest
from services.auth_service import AuthService
from core.exceptions import ConflictError, UnauthorizedError, NotFoundError, TokenInvalidError
from core import security

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

@router.post("/register", status_code=201)
async def register(
    data: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    try:
        result = await AuthService.register(db, data, client_ip, user_agent)
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return result

@router.post("/login")
async def login(
    data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    try:
        result = await AuthService.login(db, data.username, data.password, client_ip, user_agent)
    except UnauthorizedError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    return result

@router.post("/refresh")
async def refresh_token(
    data: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    client_ip = get_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    try:
        result = await AuthService.refresh(db, data.refresh_token, client_ip, user_agent)
    except (UnauthorizedError, TokenInvalidError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    return result

@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    # Здесь нужно получить токен из заголовка Authorization
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = auth_header.split(" ")[1]

    # Проверяем токен и извлекаем user_id
    valid = await AuthService.verify_token(db, token, is_refresh=False)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        payload = security.decode_jwt(token)   # нужно импортировать security
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        await AuthService.logout(db, token, user_id)
    except NotFoundError as e:
        # Если сессии нет, но мы уже проверили токен – может быть, удалена параллельно?
        # Возвращаем успех, т.к. цель достигнута
        return {"message": "Logged out successfully"}
    return {"message": "Logged out successfully"}

@router.post("/logout_all")
async def logout_all(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = auth_header.split(" ")[1]

    valid = await AuthService.verify_token(db, token, is_refresh=False)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        payload = security.decode_jwt(token)
        user_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    await AuthService.logout_all(db, user_id)
    return {"message": "All sessions logged out successfully"}