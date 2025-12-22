from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FileBase(BaseModel):
    name: str
    folder_id: Optional[int] = None


class FileRead(BaseModel):
    id: int
    name: str
    size_bytes: int
    content_type: Optional[str]
    folder_id: Optional[int]
    node_id: Optional[int] = None
    chunk_id: Optional[str] = None 
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
