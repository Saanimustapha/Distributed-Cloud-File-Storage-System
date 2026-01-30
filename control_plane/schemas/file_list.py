from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel


class FileListItem(BaseModel):
    id: int
    name: str
    folder_id: Optional[int] = None
    owner_id: int
    my_role: Optional[Literal["read", "write", "owner"]] = None

    latest_version_number: Optional[int] = None
    latest_version_size_bytes: Optional[int] = None
    latest_version_created_at: Optional[datetime] = None

    collaborator_count: Optional[int] = None

    unseen: bool = False
    last_opened_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
