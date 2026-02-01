from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel

class SearchResult(BaseModel):
    type: Literal["folder", "file"]
    id: int
    name: str

    # for folder navigation
    parent_id: Optional[int] = None

    # for files (which folder they belong to)
    folder_id: Optional[int] = None

    # if file is shared, return role to help UI enforce permissions
    my_role: Optional[str] = None

    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
