import base64
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError


def b64_decode_unpadded(s: str) -> bytes:
    s = s.strip()
    pad = (-len(s)) % 4
    return base64.b64decode(s + "=" * pad)


def ed25519_verify(public_key_b64: str, signature_b64: str, message: bytes) -> bool:
    """
    Проверяет Ed25519 подпись над сырыми байтами message.
    Клиент подписывает base64_decode(target_key) — без domain separation (v1).
    Возвращает False при любой ошибке (неверная длина ключа, битая base64, невалидная подпись).
    """
    try:
        vk = VerifyKey(b64_decode_unpadded(public_key_b64))
        vk.verify(message, b64_decode_unpadded(signature_b64))
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False
    except Exception:
        return False