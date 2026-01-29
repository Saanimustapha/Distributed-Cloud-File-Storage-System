from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import exists

from control_plane.db.session import get_db
from control_plane.models.folder import Folder
from control_plane.models.user import User
from control_plane.models.file import File as FileModel
from control_plane.schemas.folder import FolderCreate, FolderRead, FolderRename
from control_plane.schemas.folder_bulk_delete import BulkDeleteResult, SkippedFolder
from control_plane.api.routes.auth import get_current_user

router = APIRouter(prefix="/folders", tags=["folders"])


def subtree_has_any_files(db: Session, folder_id: int, owner_id: int) -> bool:
    """True if this folder OR ANY descendant folder contains files owned by the user."""
    direct = (
        db.query(exists().where(
            FileModel.folder_id == folder_id,
            FileModel.owner_id == owner_id,
        ))
        .scalar()
    )
    if direct:
        return True

    child_ids = [
        r[0]
        for r in db.query(Folder.id)
        .filter(Folder.parent_id == folder_id, Folder.owner_id == owner_id)
        .all()
    ]
    for cid in child_ids:
        if subtree_has_any_files(db, cid, owner_id):
            return True
    return False


def delete_empty_subtree(
    db: Session,
    folder_obj: Folder,
    owner_id: int,
    skipped: list,
    deleted_folders_counter: dict,
) -> bool:
    """
    Deletes folder_obj and ALL its descendants only if the whole subtree has NO files.
    Returns True if deleted, False if skipped.
    """
    if subtree_has_any_files(db, folder_obj.id, owner_id):
        skipped.append(SkippedFolder(
            id=folder_obj.id,
            name=folder_obj.name,
            reason="Folder subtree contains files",
        ))
        return False

    # Post-order delete: delete children first
    children = (
        db.query(Folder)
        .filter(Folder.parent_id == folder_obj.id, Folder.owner_id == owner_id)
        .all()
    )
    for child in children:
        delete_empty_subtree(db, child, owner_id, skipped, deleted_folders_counter)

    db.delete(folder_obj)
    deleted_folders_counter["count"] += 1
    return True


# @router.get("/all", response_model=List[FolderRead])
# def list_folders(
#     page: int = Query(1, ge=1, description="Page number (starting from 1)"),
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
#     PAGE_SIZE = 10
#     skip = (page - 1) * PAGE_SIZE
    
#     folders = (
#         db.query(Folder)
#         .filter(Folder.owner_id == current_user.id)
#         .order_by(Folder.created_at.desc())
#         .offset(skip) 
#         .limit(PAGE_SIZE)
#         .all()
#     )
#     return folders


@router.get("/all", response_model=List[FolderRead])
def list_folders(
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    parent_id: Optional[int] = Query(None, description="Parent folder ID (optional)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    PAGE_SIZE = 10
    skip = (page - 1) * PAGE_SIZE

    query = (
        db.query(Folder)
        .filter(Folder.owner_id == current_user.id)
    )

    # ✅ root-only when omitted, else children-of-parent
    if parent_id is None:
        query = query.filter(Folder.parent_id.is_(None))
    else:
        query = query.filter(Folder.parent_id == parent_id)

    folders = (
        query
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


@router.patch("/{folder_id}/rename", response_model=FolderRead, status_code=status.HTTP_200_OK)
def rename_folder(
    folder_id: int,
    payload: FolderRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Folder name cannot be empty")

    # 1) Folder must exist and belong to user
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

    # 2) No-op
    if folder.name == new_name:
        return folder

    # 3) Prevent duplicates at the same level (same parent_id)
    existing = (
        db.query(Folder)
        .filter(
            Folder.owner_id == current_user.id,
            Folder.parent_id == folder.parent_id,   # same folder level
            Folder.name == new_name,
            Folder.id != folder.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Folder with that name already exists here",
        )

    # 4) Update
    folder.name = new_name
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

#Get folder path
@router.get("/{folder_id}/path")
def get_folder_path(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # returns [{id, name}, {id, name}, ...] from root -> current
    folder = db.query(Folder).filter(
        Folder.id == folder_id,
        Folder.owner_id == current_user.id
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    path = []
    cur = folder
    # walk up parents
    while cur is not None:
        path.append({"id": cur.id, "name": cur.name, "parent_id": cur.parent_id})
        if cur.parent_id is None:
            break
        cur = db.query(Folder).filter(
            Folder.id == cur.parent_id,
            Folder.owner_id == current_user.id
        ).first()

    path.reverse()
    return path


@router.get("/{folder_id}/can-delete", response_model=dict)
def can_delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.owner_id == current_user.id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    has_files = db.query(exists().where(FileModel.folder_id == folder_id)).scalar()
    has_subfolders = db.query(exists().where(Folder.parent_id == folder_id)).scalar()

    return {
        "can_delete": (not has_files and not has_subfolders),
        "has_files": bool(has_files),
        "has_subfolders": bool(has_subfolders),
    }


@router.delete("/{folder_id}/delete-all-items", response_model=BulkDeleteResult)
def delete_all_items_in_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    root = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.owner_id == current_user.id)
        .first()
    )
    if not root:
        raise HTTPException(status_code=404, detail="Folder not found")

    deleted_files_count = 0
    skipped: list[SkippedFolder] = []
    deleted_folders_counter = {"count": 0}

    # 1) Delete files directly inside THIS folder (not recursive)
    files = (
        db.query(FileModel)
        .filter(FileModel.folder_id == folder_id, FileModel.owner_id == current_user.id)
        .all()
    )
    deleted_files_count = len(files)
    for f in files:
        db.delete(f)

    # 2) Delete child folder subtrees if they contain NO files anywhere
    top_children = (
        db.query(Folder)
        .filter(Folder.parent_id == folder_id, Folder.owner_id == current_user.id)
        .all()
    )
    for child in top_children:
        delete_empty_subtree(db, child, current_user.id, skipped, deleted_folders_counter)

    db.commit()

    return BulkDeleteResult(
        deleted_files=deleted_files_count,
        deleted_folders=deleted_folders_counter["count"],
        skipped_folders=skipped,
    )


@router.delete("/delete-all-items/root", response_model=BulkDeleteResult)
def delete_all_items_in_root(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deleted_files_count = 0
    skipped: list[SkippedFolder] = []
    deleted_folders_counter = {"count": 0}

    # 1) Delete root files (folder_id is NULL)
    root_files = (
        db.query(FileModel)
        .filter(FileModel.owner_id == current_user.id)
        .filter(FileModel.folder_id.is_(None))
        .all()
    )
    deleted_files_count = len(root_files)
    for f in root_files:
        db.delete(f)

    # 2) Delete root folder subtrees if they contain NO files anywhere
    root_folders = (
        db.query(Folder)
        .filter(Folder.owner_id == current_user.id)
        .filter(Folder.parent_id.is_(None))
        .all()
    )

    for folder in root_folders:
        delete_empty_subtree(db, folder, current_user.id, skipped, deleted_folders_counter)

    db.commit()

    return BulkDeleteResult(
        deleted_files=deleted_files_count,
        deleted_folders=deleted_folders_counter["count"],
        skipped_folders=skipped,
    )
