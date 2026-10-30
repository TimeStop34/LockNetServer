from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from core.exceptions import NotFoundError
from models.key_backup import KeyBackupVersion, KeyBackupItem


class KeyBackupService:
    @staticmethod
    async def list_versions(db: AsyncSession, user_id: int) -> list[dict]:
        stmt = select(KeyBackupVersion).where(
            KeyBackupVersion.user_id == user_id
        ).order_by(KeyBackupVersion.version)
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "version": v.version,
                "algorithm": v.algorithm,
                "auth_data": v.auth_data or {},
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in rows
        ]

    @staticmethod
    async def new_version(db: AsyncSession, user_id: int, algorithm: str, auth_data: dict) -> int:
        stmt = select(func.max(KeyBackupVersion.version)).where(
            KeyBackupVersion.user_id == user_id
        )
        max_ver = (await db.execute(stmt)).scalar()
        new_ver = (max_ver or 0) + 1
        db.add(KeyBackupVersion(
            user_id=user_id, version=new_ver,
            algorithm=algorithm, auth_data=auth_data or {},
        ))
        await db.commit()
        return new_ver

    @staticmethod
    async def put_items(db: AsyncSession, user_id: int, version: int, items: dict) -> int:
        stmt = select(KeyBackupVersion).where(
            KeyBackupVersion.user_id == user_id,
            KeyBackupVersion.version == version,
        )
        if (await db.execute(stmt)).scalar() is None:
            raise NotFoundError("backup_version_not_found")

        existing_stmt = select(KeyBackupItem.item_id).where(
            KeyBackupItem.user_id == user_id,
            KeyBackupItem.version == version,
        )
        existing = {r[0] for r in (await db.execute(existing_stmt)).all()}

        count = 0
        for item_id, data in items.items():
            if item_id in existing:
                stmt = select(KeyBackupItem).where(
                    KeyBackupItem.user_id == user_id,
                    KeyBackupItem.version == version,
                    KeyBackupItem.item_id == item_id,
                )
                row = (await db.execute(stmt)).scalar()
                row.data = data
            else:
                db.add(KeyBackupItem(
                    user_id=user_id, version=version,
                    item_id=item_id, data=data,
                ))
            count += 1
        await db.commit()
        return count

    @staticmethod
    async def get_version(db: AsyncSession, user_id: int, version: int) -> dict:
        stmt = select(KeyBackupVersion).where(
            KeyBackupVersion.user_id == user_id,
            KeyBackupVersion.version == version,
        )
        v = (await db.execute(stmt)).scalar()
        if not v:
            raise NotFoundError("backup_version_not_found")

        items_stmt = select(KeyBackupItem.item_id, KeyBackupItem.data).where(
            KeyBackupItem.user_id == user_id,
            KeyBackupItem.version == version,
        )
        items = {row[0]: row[1] for row in (await db.execute(items_stmt)).all()}
        return {
            "version": v.version,
            "algorithm": v.algorithm,
            "auth_data": v.auth_data or {},
            "items": items,
        }

    @staticmethod
    async def delete_version(db: AsyncSession, user_id: int, version: int) -> None:
        await db.execute(delete(KeyBackupItem).where(
            KeyBackupItem.user_id == user_id,
            KeyBackupItem.version == version,
        ))
        await db.execute(delete(KeyBackupVersion).where(
            KeyBackupVersion.user_id == user_id,
            KeyBackupVersion.version == version,
        ))
        await db.commit()