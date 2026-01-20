from pydantic import BaseModel, EmailStr
from datetime import datetime


class ShareFileRequest(BaseModel):
    user_id: int
    role: str  # "read" or "write"


class FileShareRead(BaseModel):
    user_id: int
    email: EmailStr
    role: str
    shared_at: datetime

    class Config:
        from_attributes = True