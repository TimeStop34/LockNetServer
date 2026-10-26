from core.ws import RequestManager, WSEndpointModel
from services.event_publisher import (
    publish_group_created_event,
    publish_group_invite_created_events,
    publish_to_group,
)
from .router import ws_router
from services.group_services import GroupService
from core.exceptions import NotFoundError, ConflictError
from core.database import AsyncSessionLocal
from pydantic import Field

# --- Модели запросов ---
class CreateDirectModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class CreateGroupModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class JoinGroupModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class LeaveGroupModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class GetGroupsModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class GetGroupInfoModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class GetInvitesModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class AcceptInviteModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

class DeclineInviteModel(WSEndpointModel):
    data: dict = Field(default_factory=dict)

# --- Обработчики ---

@ws_router.register("create_direct", CreateDirectModel)
async def handle_create_direct(user_id: int, model: CreateDirectModel, rm: RequestManager):
    other_user = model.data.get("user_id")
    if not other_user:
        await rm.send_error("user_id_required", "user_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            group = await GroupService.create_direct_logic(db, user_id, other_user)
            await publish_group_invite_created_events(group, user_id)
            await rm.send_response("create_direct", model.id, {"group": group.model_dump(mode='json')})
        except ValueError as e:
            if "Cannot create direct with yourself" in str(e):
                await rm.send_error("self_direct", "Cannot create direct with yourself", model.id)
            else:
                await rm.send_error("value_error", str(e), model.id)
        except NotFoundError:
            await rm.send_error("user_not_found", "User not found", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)

@ws_router.register("create_group", CreateGroupModel)
async def handle_create_group(user_id: int, model: CreateGroupModel, rm: RequestManager):
    data = model.data
    name = data.get("name")
    is_public = data.get("is_public", True)
    public_id = data.get("public_id")
    participant_ids = data.get("participant_ids", [])

    if not name:
        await rm.send_error("name_required", "name is required", model.id)
        return
    if is_public and not public_id:
        await rm.send_error("public_id_required", "public_id is required for public groups", model.id)
        return

    async with AsyncSessionLocal() as db:
        try:
            group = await GroupService.create_group_logic(
                db, user_id, name, is_public, public_id, participant_ids
            )

            await publish_group_created_event(group, user_id, rm.session_id)
            await publish_group_invite_created_events(group, user_id)
            await rm.send_response("create_group", model.id, {"group": group.model_dump(mode='json')})

        except ValueError as e:
            error_msg = str(e)
            if "Duplicate participant IDs" in error_msg:
                await rm.send_error("duplicate_participants", error_msg, model.id)
            elif "Creator cannot be in participant_ids" in error_msg:
                await rm.send_error("creator_in_participants", error_msg, model.id)
            elif "public_id is required for public groups" in error_msg:
                await rm.send_error("public_id_required", error_msg, model.id)
            else:
                await rm.send_error("value_error", error_msg, model.id)
        except ConflictError as e:
            if "public_id already taken" in str(e):
                await rm.send_error("public_id_taken", str(e), model.id)
            else:
                await rm.send_error("conflict", str(e), model.id)
        except NotFoundError:
            await rm.send_error("users_not_found", "One or more users not found", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)

@ws_router.register("join_group", JoinGroupModel)
async def handle_join_group(user_id: int, model: JoinGroupModel, rm: RequestManager):
    public_id = model.data.get("public_id")
    if not public_id:
        await rm.send_error("public_id_required", "public_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            group = await GroupService.join_group_logic(db, user_id, public_id)

            event_data = {
                "type": "group_membership_changed",
                "id": None,
                "data": {"group_id": group.id, "change": "added", "user_id": user_id},
            }
            await publish_to_group(group.id, event_data)

            await rm.send_response("join_group", model.id, {"group": group.model_dump(mode='json')})
        except ConflictError:
            await rm.send_error("already_member", "You are already a member of this group", model.id)
        except NotFoundError:
            await rm.send_error("group_not_public", "Group not found or not public", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)

@ws_router.register("leave_group", LeaveGroupModel)
async def handle_leave_group(user_id: int, model: LeaveGroupModel, rm: RequestManager):
    group_id = model.data.get("group_id")
    if not group_id:
        await rm.send_error("group_id_required", "group_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await GroupService.leave_group_logic(db, user_id, group_id)

            if not result.get("deleted"):
                event_data = {
                    "type": "group_membership_changed",
                    "id": None,
                    "data": {"group_id": int(group_id), "change": "left", "user_id": user_id},
                }
                await publish_to_group(int(group_id), event_data)

            await rm.send_response("leave_group", model.id, result)
        except NotFoundError as e:
            if "Not a member" in str(e):
                await rm.send_error("not_member", "You are not a member of this group", model.id)
            else:
                await rm.send_error("group_not_found", "Group not found", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)
            
@ws_router.register("get_groups", GetGroupsModel)
async def handle_get_groups(user_id: int, model: GetGroupsModel, rm: RequestManager):
    async with AsyncSessionLocal() as db:
        try:
            groups = await GroupService.get_groups_logic(db, user_id)
            groups_data = [g.model_dump(mode='json') for g in groups]
            await rm.send_response("get_groups", model.id, {"groups": groups_data})
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)

@ws_router.register("get_group_info", GetGroupInfoModel)
async def handle_get_group_info(user_id: int, model: GetGroupInfoModel, rm: RequestManager):
    group_id = model.data.get("group_id")
    if not group_id:
        await rm.send_error("group_id_required", "group_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            group = await GroupService.get_group_info_logic(db, user_id, group_id)
            await rm.send_response("get_group_info", model.id, {"group": group.model_dump(mode='json')})
        except NotFoundError:
            await rm.send_error("group_not_found", "Group not found or you are not a member", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)

# --- Приглашения ---

@ws_router.register("get_invites", GetInvitesModel)
async def handle_get_invites(user_id: int, model: GetInvitesModel, rm: RequestManager):
    async with AsyncSessionLocal() as db:
        try:
            invites = await GroupService.get_invites_logic(db, user_id)
            await rm.send_response("get_invites", model.id, {"invites": invites})
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)

@ws_router.register("accept_invite", AcceptInviteModel)
async def handle_accept_invite(user_id: int, model: AcceptInviteModel, rm: RequestManager):
    invite_id = model.data.get("invite_id")
    if not invite_id:
        await rm.send_error("invite_id_required", "invite_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await GroupService.accept_invite_logic(db, user_id, invite_id)
            await rm.send_response("accept_invite", model.id, result)
        except NotFoundError:
            await rm.send_error("invite_not_found", "Invite not found or already processed", model.id)
        except ConflictError:
            await rm.send_error("already_member", "You are already a member of this group", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)

@ws_router.register("decline_invite", DeclineInviteModel)
async def handle_decline_invite(user_id: int, model: DeclineInviteModel, rm: RequestManager):
    invite_id = model.data.get("invite_id")
    if not invite_id:
        await rm.send_error("invite_id_required", "invite_id is required", model.id)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await GroupService.decline_invite_logic(db, user_id, invite_id)
            await rm.send_response("decline_invite", model.id, result)
        except NotFoundError:
            await rm.send_error("invite_not_found", "Invite not found or already processed", model.id)
        except Exception as e:
            await rm.send_error("internal_error", f"Internal error: {e}", model.id)