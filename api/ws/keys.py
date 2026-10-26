from core.ws import RequestManager, WSEndpointModel
from .router import ws_router
from services.key_service import KeyService
from core.exceptions import NotFoundError, UnauthorizedError
from core.database import AsyncSessionLocal
from pydantic import Field


class UploadKeysModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class QueryKeysModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class ClaimOTKModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)


@ws_router.register("upload_keys", UploadKeysModel)
async def handle_upload_keys(user_id: int, model: UploadKeysModel, rm: RequestManager):
    data = model.data
    curve = data.get("curve25519_key")
    ed = data.get("ed25519_key")
    otks = data.get("one_time_keys") or {}
    sigs = data.get("signatures")
    if not curve or not ed:
        await rm.send_error("keys_required", "curve25519_key and ed25519_key are required", model.id)
        return
    try:
        async with AsyncSessionLocal() as db:
            result = await KeyService.upload_keys(
                db, user_id, rm.session_id, curve, ed, otks, sigs,
            )
        await rm.send_response("upload_keys", model.id, result)
    except UnauthorizedError:
        await rm.send_error("unauthorized", "Session not found", model.id)
    except NotFoundError:
        await rm.send_error("self_signing_key_not_found", "Self-signing key not found", model.id)
    except ValueError as e:
        await rm.send_error("invalid_signature", str(e), model.id)
    except Exception as e:
        await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("query_keys", QueryKeysModel)
async def handle_query_keys(user_id: int, model: QueryKeysModel, rm: RequestManager):
    user_ids = model.data.get("user_ids") or []
    if not user_ids:
        await rm.send_error("user_ids_required", "user_ids is required", model.id)
        return
    try:
        async with AsyncSessionLocal() as db:
            result = await KeyService.query_keys(db, user_ids)
        await rm.send_response("query_keys", model.id, result)
    except Exception as e:
        await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("claim_one_time_key", ClaimOTKModel)
async def handle_claim_one_time_key(user_id: int, model: ClaimOTKModel, rm: RequestManager):
    target_user_id = model.data.get("user_id")
    target_session_id = model.data.get("session_id")
    algorithm = model.data.get("algorithm", "curve25519")
    if not target_user_id or not target_session_id:
        await rm.send_error("user_id_and_session_id_required", "user_id and session_id are required", model.id)
        return
    try:
        async with AsyncSessionLocal() as db:
            result = await KeyService.claim_one_time_key(
                db, int(target_user_id), int(target_session_id), algorithm,
            )
        await rm.send_response("claim_one_time_key", model.id, result)
    except NotFoundError as e:
        msg = str(e)
        if "no_one_time_keys" in msg:
            await rm.send_error("no_one_time_keys", "No one-time keys left for this session", model.id)
        else:
            await rm.send_error("session_not_found", "Session not found", model.id)
    except Exception as e:
        await rm.send_error("internal_error", f"Internal error: {e}", model.id)