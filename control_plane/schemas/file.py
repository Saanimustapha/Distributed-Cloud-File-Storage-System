from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FileBase(BaseModel):
    name: str
    folder_id: Optional[int] = None


class FileRead(BaseModel):
    id: int
    name: str
    folder_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
