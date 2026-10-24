# Импортируем все файлы с обработчиками, чтобы декораторы сработали
from . import ping
from . import group
from . import event

# Экспортируем роутер для использования в websocket.py
from .router import ws_router

__all__ = ["ws_router"]