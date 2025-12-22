from datetime import datetime
from typing import Optional
from pydantic import BaseModel, AnyHttpUrl


class NodeBase(BaseModel):
    name: str
    base_url: AnyHttpUrl
    is_online: bool = True
    capacity_bytes: Optional[int] = None


class NodeCreate(NodeBase):
    pass


class NodeRead(NodeBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
