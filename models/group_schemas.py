from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class GroupMemberInfo(BaseModel):
    user_id: int
    is_mod: bool

class FullGroup(BaseModel):
    id: int
    public_id: Optional[str]
    name: str
    is_public: bool
    created_by: int
    created_at: datetime
    updated_at: datetime
    members: Optional[List[GroupMemberInfo]]
    member_count: int

class GroupCreate(BaseModel):
    name: str
    is_public: bool = True
    public_id: Optional[str] = None
    participant_ids: List[int] = []