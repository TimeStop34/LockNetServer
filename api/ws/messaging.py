from core.ws import RequestManager, WSEndpointModel
from .router import ws_router
from services.message_service import MessageService
from services.reaction_service import ReactionService
from core.exceptions import NotFoundError, UnauthorizedError
from core.database import AsyncSessionLocal
from pydantic import Field


class SendMessageModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class GetMessagesModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class EditMessageModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class DeleteMessageModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class AddReactionModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class RemoveReactionModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class SendToDeviceModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)


@ws_router.register("send_message", SendMessageModel)
async def handle_send_message(user_id: int, model: SendMessageModel, rm: RequestManager):
    chat_id = model.data.get("chat_id")
    encrypted = model.data.get("encrypted")
    if not chat_id:
        await rm.send_error("chat_id_required", "chat_id is required", model.id)
        return
    if not isinstance(encrypted, dict):
        await rm.send_error("invalid_encrypted", "encrypted must be an object", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await MessageService.send(db, user_id, rm.session_id, int(chat_id), encrypted)
            await rm.send_response("send_message", model.id, result)
        except NotFoundError as e:
            await rm.send_error("chat_not_found", str(e), model.id)
        except UnauthorizedError:
            await rm.send_error("not_a_member", "Not a member of this chat", model.id)
        except ValueError as e:
            await rm.send_error(str(e).split(":")[0] if ":" in str(e) else str(e), str(e), model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("send_to_device", SendToDeviceModel)
async def handle_send_to_device(user_id: int, model: SendToDeviceModel, rm: RequestManager):
    messages = model.data.get("messages")
    if not isinstance(messages, dict):
        await rm.send_error("messages_required", "messages must be an object", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await MessageService.send_to_device(db, user_id, rm.session_id, messages)
            await rm.send_response("send_to_device", model.id, result)
        except UnauthorizedError as e:
            await rm.send_error("unauthorized", str(e), model.id)
        except ValueError as e:
            await rm.send_error("invalid_payload", str(e), model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("get_messages", GetMessagesModel)
async def handle_get_messages(user_id: int, model: GetMessagesModel, rm: RequestManager):
    chat_id = model.data.get("chat_id")
    before = model.data.get("before")
    limit = model.data.get("limit", 50)
    if not chat_id:
        await rm.send_error("chat_id_required", "chat_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await MessageService.get_messages(db, user_id, int(chat_id), before, int(limit))
            await rm.send_response("get_messages", model.id, result)
        except NotFoundError:
            await rm.send_error("chat_not_found", "Chat not found", model.id)
        except UnauthorizedError:
            await rm.send_error("not_a_member", "Not a member of this chat", model.id)
        except ValueError:
            await rm.send_error("invalid_limit", "limit must be between 1 and 100", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("edit_message", EditMessageModel)
async def handle_edit_message(user_id: int, model: EditMessageModel, rm: RequestManager):
    message_id = model.data.get("message_id")
    encrypted = model.data.get("encrypted")
    if not message_id:
        await rm.send_error("message_id_required", "message_id is required", model.id)
        return
    if not isinstance(encrypted, dict):
        await rm.send_error("invalid_encrypted", "encrypted must be an object", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await MessageService.edit(db, user_id, rm.session_id, int(message_id), encrypted)
            await rm.send_response("edit_message", model.id, result)
        except NotFoundError:
            await rm.send_error("message_not_found", "Message not found", model.id)
        except UnauthorizedError:
            await rm.send_error("not_author", "Only the author can edit this message", model.id)
        except ValueError as e:
            msg = str(e)
            code = msg.split(":")[0] if ":" in msg else msg
            await rm.send_error(code, msg, model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("delete_message", DeleteMessageModel)
async def handle_delete_message(user_id: int, model: DeleteMessageModel, rm: RequestManager):
    message_id = model.data.get("message_id")
    if not message_id:
        await rm.send_error("message_id_required", "message_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await MessageService.delete(db, user_id, int(message_id))
            await rm.send_response("delete_message", model.id, result)
        except NotFoundError:
            await rm.send_error("message_not_found", "Message not found", model.id)
        except UnauthorizedError:
            await rm.send_error("forbidden", "You cannot delete this message", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("add_reaction", AddReactionModel)
async def handle_add_reaction(user_id: int, model: AddReactionModel, rm: RequestManager):
    message_id = model.data.get("message_id")
    emoji = model.data.get("emoji")
    if not message_id or not emoji:
        await rm.send_error("invalid_emoji", "message_id and emoji are required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await ReactionService.add(db, user_id, int(message_id), emoji)
            await rm.send_response("add_reaction", model.id, result)
        except NotFoundError:
            await rm.send_error("message_not_found", "Message not found", model.id)
        except UnauthorizedError:
            await rm.send_error("not_a_member", "Not a member of this chat", model.id)
        except ValueError as e:
            msg = str(e)
            if "message_deleted" in msg:
                await rm.send_error("message_deleted", "Message is deleted", model.id)
            elif "invalid_emoji" in msg:
                await rm.send_error("invalid_emoji", "Invalid emoji", model.id)
            else:
                await rm.send_error("invalid_emoji", msg, model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)


@ws_router.register("remove_reaction", RemoveReactionModel)
async def handle_remove_reaction(user_id: int, model: RemoveReactionModel, rm: RequestManager):
    message_id = model.data.get("message_id")
    emoji = model.data.get("emoji")
    if not message_id or not emoji:
        await rm.send_error("invalid_emoji", "message_id and emoji are required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await ReactionService.remove(db, user_id, int(message_id), emoji)
            await rm.send_response("remove_reaction", model.id, result)
        except NotFoundError as e:
            if "reaction_not_found" in str(e):
                await rm.send_error("reaction_not_found", "Reaction not found", model.id)
            else:
                await rm.send_error("message_not_found", "Message not found", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)