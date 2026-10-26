from core.ws import RequestManager, WSEndpointModel
from .router import ws_router
from services.cross_signing_service import CrossSigningService
from services.event_services import EventService
from core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from core.database import AsyncSessionLocal
from pydantic import Field


class UploadCrossSigningKeysModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class UploadSignaturesModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class QueryCrossSigningKeysModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)


@ws_router.register("upload_cross_signing_keys", UploadCrossSigningKeysModel)
async def handle_upload_cross_signing_keys(user_id: int, model: UploadCrossSigningKeysModel, rm: RequestManager):
    data = model.data
    try:
        async with AsyncSessionLocal() as db:
            await CrossSigningService.upload_cross_signing_keys(
                db, user_id,
                master_key=data.get("master_key") or {},
                self_signing_key=data.get("self_signing_key") or {},
                user_signing_key=data.get("user_signing_key") or {},
            )
        await rm.send_response("upload_cross_signing_keys", model.id, {})
    except ConflictError:
        await rm.send_error("cross_signing_already_exists", "Cross-signing keys already uploaded", model.id)
    except ValueError as e:
        await rm.send_error("invalid_signature", str(e), model.id)
    except Exception as e:
        await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("upload_signatures", UploadSignaturesModel)
async def handle_upload_signatures(user_id: int, model: UploadSignaturesModel, rm: RequestManager):
    user_signatures = model.data.get("user_signatures") or {}
    device_signatures = model.data.get("device_signatures") or {}
    try:
        async with AsyncSessionLocal() as db:
            result = await CrossSigningService.upload_signatures(
                db, user_id, user_signatures, device_signatures,
            )
            # Push to each target user whose MSK we signed
            for target_uid_str, sig in user_signatures.items():
                target_uid = int(target_uid_str)
                event_data = {
                    "type": "cross_signing_signature_added",
                    "id": None,
                    "data": {
                        "signer_user_id": user_id,
                        "key_type": "user_signing",
                        "target": "master",
                        "signature": sig,
                    },
                }
                await EventService.create_event(db, target_uid, event_data)
        await rm.send_response("upload_signatures", model.id, result)
    except NotFoundError as e:
        await rm.send_error("not_found", str(e), model.id)
    except UnauthorizedError as e:
        await rm.send_error("unauthorized", str(e), model.id)
    except ValueError as e:
        await rm.send_error("invalid_signature", str(e), model.id)
    except Exception as e:
        await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("query_cross_signing_keys", QueryCrossSigningKeysModel)
async def handle_query_cross_signing_keys(user_id: int, model: QueryCrossSigningKeysModel, rm: RequestManager):
    user_ids = model.data.get("user_ids") or []
    if not user_ids:
        await rm.send_error("user_ids_required", "user_ids is required", model.id)
        return
    try:
        async with AsyncSessionLocal() as db:
            result = await CrossSigningService.query_cross_signing_keys(db, user_ids)
        await rm.send_response("query_cross_signing_keys", model.id, result)
    except Exception as e:
        await rm.send_error("internal_error", f"Internal error: {e}", model.id)