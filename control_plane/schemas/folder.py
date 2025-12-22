from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class FolderBase(BaseModel):
    name: str
    parent_id: Optional[int] = None


class FolderCreate(FolderBase):
    pass


class FolderRead(FolderBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
