from pydantic import BaseModel
from typing import List, Optional

class SkippedFolder(BaseModel):
    id: int
    name: str
    reason: str

class BulkDeleteResult(BaseModel):
    deleted_files: int
    deleted_folders: int

class DeleteFolderTreeResult(BaseModel):
    deleted_files: int
    deleted_folders: int
