from pydantic import BaseModel


class ShareFileRequest(BaseModel):
    user_id: int
    role: str  # "read" or "write"
