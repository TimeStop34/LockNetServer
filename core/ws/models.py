from pydantic import BaseModel
from typing import Any, Dict, Optional

class WSEndpointModel(BaseModel):
    """Базовая модель для входящего WebSocket-запроса."""
    id: Optional[str] = None
    data: Dict[str, Any] = {}

class WSResponseModel(BaseModel):
    """Модель для ответа (если требуется отдельная валидация)."""
    id: str
    data: Dict[str, Any] = {}