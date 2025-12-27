from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import exists

from control_plane.db.session import get_db
from control_plane.models.folder import Folder
from control_plane.models.user import User
from control_plane.models.file import File as FileModel
from control_plane.schemas.folder import FolderCreate, FolderRead
from control_plane.api.routes.auth import get_current_user

router = APIRouter(prefix="/folders", tags=["folders"])


@router.get("/all", response_model=List[FolderRead])
def list_folders(
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    PAGE_SIZE = 10
    skip = (page - 1) * PAGE_SIZE
    
    folders = (
        db.query(Folder)
        .filter(Folder.owner_id == current_user.id)
        .order_by(Folder.created_at.desc())
        .offset(skip) 
        .limit(PAGE_SIZE)
        .all()
    )
    return folders


@router.post("/create", response_model=FolderRead, status_code=status.HTTP_201_CREATED)
def create_folder(
    payload: FolderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Optional: prevent duplicate names at same level
    existing = (
        db.query(Folder)
        .filter(
            Folder.owner_id == current_user.id,
            Folder.name == payload.name,
            Folder.parent_id == payload.parent_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Folder with that name already exists here")

    folder = Folder(
        name=payload.name,
        owner_id=current_user.id,
        parent_id=payload.parent_id,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.delete("/delete/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1) Folder must exist and belong to current user
    folder = (
        db.query(Folder)
        .filter(
            Folder.id == folder_id,
            Folder.owner_id == current_user.id,
        )
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # 2) Reject deletion if folder still contains files
    has_files = db.query(
        exists().where(FileModel.folder_id == folder_id)
    ).scalar()

    if has_files:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Folder is not empty. Move or delete files first.",
        )

    # also reject if folder contains subfolders, if you support nesting
    has_subfolders = db.query(exists().where(Folder.parent_id == folder_id)).scalar()
    if has_subfolders:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Folder contains subfolders. Delete/move them first.",
        )

    # 3) Delete the folder
    db.delete(folder)
    db.commit()

    return {"message": "Folder deleted successfully"}