from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime, timezone

from core import security
from core.ed25519_utils import ed25519_verify, b64_decode_unpadded
from core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from models.user import User
from models.user_cross_signing_key import UserCrossSigningKey
from models.session import Session as SessionModel


class CrossSigningService:
    @staticmethod
    async def upload_cross_signing_keys(
        db: AsyncSession,
        user_id: int,
        master_key: dict,
        self_signing_key: dict,
        user_signing_key: dict,
    ) -> None:
        # 1. First-time only (v1)
        stmt = select(UserCrossSigningKey.user_id).where(
            UserCrossSigningKey.user_id == user_id
        ).limit(1)
        if (await db.execute(stmt)).scalar() is not None:
            raise ConflictError("Cross-signing keys already uploaded")

        msk = master_key.get("key")
        ssk = self_signing_key.get("key")
        usk = user_signing_key.get("key")
        if not msk or not ssk or not usk:
            raise ValueError("All three keys are required")

        # 2. SSK и USK должны быть подписаны MSK
        ssk_sigs = self_signing_key.get("signatures") or {}
        usk_sigs = user_signing_key.get("signatures") or {}
        ssk_sig = (ssk_sigs.get(str(user_id)) or {}).get("master")
        usk_sig = (usk_sigs.get(str(user_id)) or {}).get("master")

        if not ssk_sig or not usk_sig:
            raise ValueError("SSK and USK must be signed by master key")

        # 3. Серверная Ed25519-валидация подписей
        if not ed25519_verify(msk, ssk_sig, b64_decode_unpadded(ssk)):
            raise ValueError("Invalid SSK signature from MSK")
        if not ed25519_verify(msk, usk_sig, b64_decode_unpadded(usk)):
            raise ValueError("Invalid USK signature from MSK")

        # 4. Сохраняем три ключа
        db.add(UserCrossSigningKey(
            user_id=user_id, key_type="master",
            key_value=msk, signatures=master_key.get("signatures") or {},
        ))
        db.add(UserCrossSigningKey(
            user_id=user_id, key_type="self_signing",
            key_value=ssk, signatures=ssk_sigs,
        ))
        db.add(UserCrossSigningKey(
            user_id=user_id, key_type="user_signing",
            key_value=usk, signatures=usk_sigs,
        ))
        await db.commit()

    @staticmethod
    async def upload_signatures(
        db: AsyncSession,
        signer_user_id: int,
        user_signatures: dict[str, str],
        device_signatures: dict[str, str],
    ) -> dict:
        # Ключи подписанта
        stmt = select(UserCrossSigningKey).where(
            UserCrossSigningKey.user_id == signer_user_id
        )
        rows = (await db.execute(stmt)).scalars().all()
        own_keys = {r.key_type: r for r in rows}
        usk = own_keys.get("user_signing")
        ssk = own_keys.get("self_signing")

        updated_users = 0
        updated_devices = 0

        # user_signatures: наш USK подписывает чужой MSK
        for target_uid_str, sig in (user_signatures or {}).items():
            target_uid = int(target_uid_str)
            if target_uid == signer_user_id:
                raise ValueError("Cannot sign own master key with USK")
            if not usk:
                raise NotFoundError("Signer has no user_signing key")

            stmt = select(UserCrossSigningKey).where(
                UserCrossSigningKey.user_id == target_uid,
                UserCrossSigningKey.key_type == "master",
            )
            target_msk = (await db.execute(stmt)).scalar()
            if not target_msk:
                raise NotFoundError(f"Target master key not found: {target_uid}")

            if not ed25519_verify(usk.key_value, sig, b64_decode_unpadded(target_msk.key_value)):
                raise ValueError(f"Invalid signature for user {target_uid}")

            sigs = dict(target_msk.signatures or {})
            sigs.setdefault(str(signer_user_id), {})["user_signing"] = sig
            target_msk.signatures = sigs
            updated_users += 1

        # device_signatures: наш SSK подписывает СВОЮ сессию
        for target_sid_str, sig in (device_signatures or {}).items():
            target_sid = int(target_sid_str)
            target_session = await db.get(SessionModel, target_sid)
            if not target_session:
                raise NotFoundError(f"Session not found: {target_sid}")
            if target_session.user_id != signer_user_id:
                raise UnauthorizedError("Can only sign own sessions")
            if not ssk:
                raise NotFoundError("Signer has no self_signing key")
            if not target_session.ed25519_key:
                raise ValueError(f"Session {target_sid} has no ed25519_key")

            if not ed25519_verify(ssk.key_value, sig, b64_decode_unpadded(target_session.ed25519_key)):
                raise ValueError(f"Invalid signature for session {target_sid}")

            sigs = dict(target_session.signatures or {})
            sigs.setdefault(str(signer_user_id), {})["self_signing"] = sig
            target_session.signatures = sigs
            updated_devices += 1

        await db.commit()
        return {"users_updated": updated_users, "devices_updated": updated_devices}

    @staticmethod
    async def query_cross_signing_keys(
        db: AsyncSession,
        user_ids: list[int],
    ) -> dict:
        now = datetime.now(timezone.utc)
        result = {}

        for uid in user_ids:
            # Все три ключа пользователя
            stmt = select(UserCrossSigningKey).where(UserCrossSigningKey.user_id == uid)
            rows = (await db.execute(stmt)).scalars().all()
            keys = {r.key_type: r for r in rows}
            if "master" not in keys:
                continue  # пользователь ещё не настроил cross-signing

            # Активные устройства с ed25519_key
            stmt = select(SessionModel).where(
                SessionModel.user_id == uid,
                SessionModel.expires_at > now,
                SessionModel.ed25519_key.isnot(None),
            )
            sessions = (await db.execute(stmt)).scalars().all()

            devices = {}
            for s in sessions:
                devices[str(s.id)] = {
                    "ed25519_key": s.ed25519_key,
                    "curve25519_key": s.curve25519_key,
                    "signatures": s.signatures or {},
                }

            entry = {
                "master_key": {
                    "key": keys["master"].key_value,
                    "signatures": keys["master"].signatures or {},
                },
                "devices": devices,
            }
            if "self_signing" in keys:
                entry["self_signing_key"] = {
                    "key": keys["self_signing"].key_value,
                    "signatures": keys["self_signing"].signatures or {},
                }
            if "user_signing" in keys:
                entry["user_signing_key"] = {
                    "key": keys["user_signing"].key_value,
                    "signatures": keys["user_signing"].signatures or {},
                }
            result[str(uid)] = entry

        return result

    @staticmethod
    async def reset_cross_signing_keys(
        db: AsyncSession,
        user_id: int,
        password: str,
    ) -> dict:
        # 1. Пароль — защита от случайного/чужого сброса (UIA)
        user = await db.get(User, user_id)
        if not user or not security.verify_password(password, user.password_hash):
            raise UnauthorizedError("Invalid password")

        affected_users: set[int] = set()

        # 2. Собираем signers: тех, кто подписал НАШ MSK своим USK.
        #    Их подписи будут аннулированы вместе с удалением user_cross_signing_keys[user_id],
        #    поэтому их тоже надо уведомить (push cross_signing_reset).
        stmt = select(UserCrossSigningKey).where(
            UserCrossSigningKey.user_id == user_id,
            UserCrossSigningKey.key_type == "master",
        )
        own_msk = (await db.execute(stmt)).scalar()
        if own_msk:
            for signer_uid_str in (own_msk.signatures or {}).keys():
                try:
                    signer_uid = int(signer_uid_str)
                except (ValueError, TypeError):
                    continue
                if signer_uid != user_id:
                    affected_users.add(signer_uid)

        # 3. Удаляем все свои cross-signing ключи (MSK/SSK/USK)
        await db.execute(
            delete(UserCrossSigningKey).where(UserCrossSigningKey.user_id == user_id)
        )

        # 4. Убираем свои SSK-подписи из своих сессий
        stmt = select(SessionModel).where(SessionModel.user_id == user_id)
        own_sessions = (await db.execute(stmt)).scalars().all()
        for s in own_sessions:
            sigs = dict(s.signatures or {})
            if str(user_id) in sigs:
                del sigs[str(user_id)]
                s.signatures = sigs

        # 5. Убираем свои USK-подписи из чужих MSK
        stmt = select(UserCrossSigningKey).where(
            UserCrossSigningKey.key_type == "master",
            UserCrossSigningKey.user_id != user_id,
        )
        for msk in (await db.execute(stmt)).scalars().all():
            sigs = dict(msk.signatures or {})
            if str(user_id) in sigs:
                del sigs[str(user_id)]
                msk.signatures = sigs
                affected_users.add(msk.user_id)

        await db.commit()
        return {"affected_users": sorted(affected_users)}