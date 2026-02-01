from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from control_plane.db.session import get_db
from control_plane.api.routes.auth import get_current_user
from control_plane.models.user import User
from control_plane.models.folder import Folder
from control_plane.models.file import File as FileModel
from control_plane.models.file_permission import FilePermission
from control_plane.schemas.search import SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=List[SearchResult])
def search_files_and_folders(
    q: str = Query(..., min_length=1, description="Search text"),
    limit: int = Query(10, ge=1, le=30),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q_like = f"%{q.strip()}%"

    # 1) Folders owned by user
    folders = (
        db.query(Folder)
        .filter(
            Folder.owner_id == current_user.id,
            Folder.name.ilike(q_like),
        )
        .order_by(Folder.created_at.desc())
        .limit(limit)
        .all()
    )

    folder_results = [
        SearchResult(
            type="folder",
            id=f.id,
            name=f.name,
            parent_id=f.parent_id,
            created_at=f.created_at,
        )
        for f in folders
    ]

    # 2) Files owned by user
    owned_files = (
        db.query(FileModel)
        .filter(
            FileModel.owner_id == current_user.id,
            FileModel.name.ilike(q_like),
        )
        .order_by(FileModel.updated_at.desc())
        .limit(limit)
        .all()
    )

    owned_file_results = [
        SearchResult(
            type="file",
            id=f.id,
            name=f.name,
            folder_id=f.folder_id,
            my_role="owner",
            updated_at=f.updated_at,
        )
        for f in owned_files
    ]

    # 3) Files shared with user (optional but recommended)
    shared_rows = (
        db.query(FileModel, FilePermission.role)
        .join(FilePermission, FilePermission.file_id == FileModel.id)
        .filter(
            FilePermission.user_id == current_user.id,
            FileModel.owner_id != current_user.id,
            FileModel.name.ilike(q_like),
        )
        .order_by(FileModel.updated_at.desc())
        .limit(limit)
        .all()
    )

    shared_file_results = [
        SearchResult(
            type="file",
            id=f.id,
            name=f.name,
            folder_id=f.folder_id,
            my_role=role,
            updated_at=f.updated_at,
        )
        for (f, role) in shared_rows
    ]

    # merge + sort, then take final limit
    all_results = folder_results + owned_file_results + shared_file_results
    all_results.sort(key=lambda x: x.updated_at or 0, reverse=True)

    return all_results[:limit]
