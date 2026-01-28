from pydantic import BaseModel

class GoogleLoginRequest(BaseModel):
    id_token: str
