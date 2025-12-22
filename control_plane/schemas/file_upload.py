from pydantic import BaseModel
from control_plane.schemas.file import FileRead
from control_plane.schemas.file_version import FileVersionRead


class FileUploadResponse(BaseModel):
    file: FileRead
    version: FileVersionRead
