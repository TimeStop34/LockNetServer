from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone
from core.ed25519_utils import ed25519_verify, b64_decode_unpadded
from core.exceptions import NotFoundError, UnauthorizedError
from models.session import Session as SessionModel
from models.session_one_time_key import SessionOneTimeKey
from models.user_cross_signing_key import UserCrossSigningKey


class KeyService:
    @staticmethod
    async def upload_keys(
        db: AsyncSession,
        user_id: int,
        session_id: int,
        curve25519_key: str,
        ed25519_key: str,
        one_time_keys: dict[str, str],
        signatures: dict | None = None,
    ) -> dict:
        session = await db.get(SessionModel, session_id)
        if not session or session.user_id != user_id:
            raise UnauthorizedError("Session not found")

        session.curve25519_key = curve25519_key
        session.ed25519_key = ed25519_key

        # Optional self-signing signature (from own SSK)
        if signatures:
            own_sigs = signatures.get(str(user_id)) or {}
            ssk_sig = own_sigs.get("self_signing")
            if ssk_sig:
                stmt = select(UserCrossSigningKey).where(
                    UserCrossSigningKey.user_id == user_id,
                    UserCrossSigningKey.key_type == "self_signing",
                )
                ssk = (await db.execute(stmt)).scalar()
                if not ssk:
                    raise NotFoundError("self_signing_key_not_found")
                if not ed25519_verify(ssk.key_value, ssk_sig, b64_decode_unpadded(ed25519_key)):
                    raise ValueError("Invalid self-signing signature")

                sigs = dict(session.signatures or {})
                sigs.setdefault(str(user_id), {})["self_signing"] = ssk_sig
                session.signatures = sigs

        # Insert OTKs (skip existing)
        for key_id, key_value in (one_time_keys or {}).items():
            algorithm = key_id.split(":", 1)[0] if ":" in key_id else "curve25519"

            stmt = select(SessionOneTimeKey.key_id).where(
                SessionOneTimeKey.session_id == session_id,
                SessionOneTimeKey.key_id == key_id,
            )
            if (await db.execute(stmt)).scalar() is None:
                db.add(SessionOneTimeKey(
                    session_id=session_id,
                    key_id=key_id,
                    key_value=key_value,
                    algorithm=algorithm,
                ))

        await db.commit()

        stmt = select(SessionOneTimeKey.algorithm, func.count()).where(
            SessionOneTimeKey.session_id == session_id,
        ).group_by(SessionOneTimeKey.algorithm)
        rows = (await db.execute(stmt)).all()
        counts = {alg: cnt for alg, cnt in rows}
        return {"one_time_key_counts": counts}

    @staticmethod
    async def query_keys(db: AsyncSession, user_ids: list[int]) -> dict:
        now = datetime.now(timezone.utc)
        result = {}
        for uid in user_ids:
            stmt = select(SessionModel).where(
                SessionModel.user_id == uid,
                SessionModel.expires_at > now,
                SessionModel.curve25519_key.isnot(None),
                SessionModel.ed25519_key.isnot(None),
            )
            sessions = (await db.execute(stmt)).scalars().all()
            if not sessions:
                continue
            devices = {}
            for s in sessions:
                devices[str(s.id)] = {
                    "curve25519_key": s.curve25519_key,
                    "ed25519_key": s.ed25519_key,
                }
            result[str(uid)] = devices
        return result

    @staticmethod
    async def claim_one_time_key(
        db: AsyncSession,
        target_user_id: int,
        target_session_id: int,
        algorithm: str = "curve25519",
    ) -> dict:
        session = await db.get(SessionModel, target_session_id)
        if not session or session.user_id != target_user_id:
            raise NotFoundError("session_not_found")

        stmt = (
            select(SessionOneTimeKey)
            .where(
                SessionOneTimeKey.session_id == target_session_id,
                SessionOneTimeKey.algorithm == algorithm,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        otk = (await db.execute(stmt)).scalar()
        if not otk:
            raise NotFoundError("no_one_time_keys")

        key_id, key_value = otk.key_id, otk.key_value
        await db.delete(otk)
        await db.commit()
        return {"key_id": key_id, "key": key_value}