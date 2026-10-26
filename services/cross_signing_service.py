from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from core.ed25519_utils import ed25519_verify, b64_decode_unpadded
from core.exceptions import ConflictError, NotFoundError, UnauthorizedError
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
        # 1. Already exists? (v1: first-time only)
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

        # 2. Extract signatures from SSK/USK (must be signed by own MSK)
        ssk_sigs = self_signing_key.get("signatures") or {}
        usk_sigs = user_signing_key.get("signatures") or {}
        ssk_sig = (ssk_sigs.get(str(user_id)) or {}).get("master")
        usk_sig = (usk_sigs.get(str(user_id)) or {}).get("master")

        if not ssk_sig or not usk_sig:
            raise ValueError("SSK and USK must be signed by master key")

        # 3. Verify Ed25519 (server-side, per point ⚠️)
        if not ed25519_verify(msk, ssk_sig, b64_decode_unpadded(ssk)):
            raise ValueError("Invalid SSK signature from MSK")
        if not ed25519_verify(msk, usk_sig, b64_decode_unpadded(usk)):
            raise ValueError("Invalid USK signature from MSK")

        # 4. Insert
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
        # Load signer's cross-signing keys
        stmt = select(UserCrossSigningKey).where(
            UserCrossSigningKey.user_id == signer_user_id
        )
        rows = (await db.execute(stmt)).scalars().all()
        own_keys = {r.key_type: r for r in rows}
        usk = own_keys.get("user_signing")
        ssk = own_keys.get("self_signing")

        updated_users = 0
        updated_devices = 0

        # --- user_signatures: USK(signer) signs MSK(target) ---
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

        # --- device_signatures: SSK(signer) signs own session's ed25519 ---
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
            stmt = select(UserCrossSigningKey).where(UserCrossSigningKey.user_id == uid)
            rows = (await db.execute(stmt)).scalars().all()
            keys = {r.key_type: r for r in rows}
            if "master" not in keys:
                continue  # user hasn't set up cross-signing

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