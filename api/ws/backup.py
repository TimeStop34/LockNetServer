from core.ws import RequestManager, WSEndpointModel
from .router import ws_router
from services.key_backup_service import KeyBackupService
from core.exceptions import NotFoundError
from core.database import AsyncSessionLocal
from pydantic import Field


class BackupVersionsModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class BackupNewModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class BackupPutModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class BackupGetModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class BackupDeleteModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)


@ws_router.register("backup_versions", BackupVersionsModel)
async def handle_backup_versions(user_id: int, model: BackupVersionsModel, rm: RequestManager):
    async with AsyncSessionLocal() as db:
        try:
            versions = await KeyBackupService.list_versions(db, user_id)
            await rm.send_response("backup_versions", model.id, {"versions": versions})
        except Exception as e:
            await rm.send_error("internal_error", str(e), model.id)


@ws_router.register("backup_new", BackupNewModel)
async def handle_backup_new(user_id: int, model: BackupNewModel, rm: RequestManager):
    algorithm = model.data.get("algorithm")
    auth_data = model.data.get("auth_data") or {}
    if not algorithm:
        await rm.send_error("algorithm_required", "algorithm is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            v = await KeyBackupService.new_version(db, user_id, algorithm, auth_data)
            await rm.send_response("backup_new", model.id, {"version": v})
        except Exception as e:
            await rm.send_error("internal_error", str(e), model.id)


@ws_router.register("backup_put", BackupPutModel)
async def handle_backup_put(user_id: int, model: BackupPutModel, rm: RequestManager):
    version = model.data.get("version")
    items = model.data.get("items")
    if not isinstance(version, int) or not isinstance(items, dict):
        await rm.send_error("invalid_payload", "version (int) and items (dict) required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            count = await KeyBackupService.put_items(db, user_id, version, items)
            await rm.send_response("backup_put", model.id, {"count": count})
        except NotFoundError:
            await rm.send_error("backup_version_not_found", "Backup version not found", model.id)
        except Exception as e:
            await rm.send_error("internal_error", str(e), model.id)


@ws_router.register("backup_get", BackupGetModel)
async def handle_backup_get(user_id: int, model: BackupGetModel, rm: RequestManager):
    version = model.data.get("version")
    if not isinstance(version, int):
        await rm.send_error("invalid_payload", "version (int) required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            data = await KeyBackupService.get_version(db, user_id, version)
            await rm.send_response("backup_get", model.id, data)
        except NotFoundError:
            await rm.send_error("backup_version_not_found", "Backup version not found", model.id)
        except Exception as e:
            await rm.send_error("internal_error", str(e), model.id)


@ws_router.register("backup_delete", BackupDeleteModel)
async def handle_backup_delete(user_id: int, model: BackupDeleteModel, rm: RequestManager):
    version = model.data.get("version")
    if not isinstance(version, int):
        await rm.send_error("invalid_payload", "version (int) required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            await KeyBackupService.delete_version(db, user_id, version)
            await rm.send_response("backup_delete", model.id, {})
        except Exception as e:
            await rm.send_error("internal_error", str(e), model.id)