from pydantic import BaseModel
from datetime import datetime

class FileVersionRead(BaseModel):
    id: int
    version_number: int
    size_bytes: int
    created_at: datetime

    class Config:
        from_attributes = True
