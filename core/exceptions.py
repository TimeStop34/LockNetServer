class AppException(Exception):
    """Базовое исключение приложения."""
    pass

class ConflictError(AppException):
    """Конфликт (например, имя пользователя уже занято)."""
    pass

class UnauthorizedError(AppException):
    """Неверные учётные данные или отсутствие прав."""
    pass

class NotFoundError(AppException):
    """Объект не найден."""
    pass

class TokenInvalidError(AppException):
    """Невалидный токен."""
    pass