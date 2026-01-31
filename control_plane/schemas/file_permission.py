from pydantic import BaseModel, EmailStr, Field
from typing import List, Literal
from datetime import datetime


class ShareFileRequest(BaseModel):
    user_ids: List[int] = Field(..., min_length=1)
    role: Literal["read", "write"]


class FileShareRead(BaseModel):
    user_id: int
    email: EmailStr
    role: str
    shared_at: datetime

    class Config:
        from_attributes = True