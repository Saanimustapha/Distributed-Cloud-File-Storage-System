from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, aliased
from sqlalchemy import exists, delete
from sqlalchemy.exc import SQLAlchemyError

from control_plane.db.session import get_db
from control_plane.models.folder import Folder
from control_plane.models.user import User
from control_plane.models.file import File as FileModel
from control_plane.models.chunk import Chunk
from control_plane.models.chunk_locations import ChunkLocation
from control_plane.models.file_versions import FileVersion
from control_plane.schemas.folder import FolderCreate, FolderRead, FolderRename
from control_plane.schemas.folder_bulk_delete import BulkDeleteResult, SkippedFolder
from control_plane.schemas.folder_bulk_delete import DeleteFolderTreeResult
from control_plane.api.routes.auth import get_current_user


router = APIRouter(prefix="/folders", tags=["folders"])



def get_descendant_folder_ids(db: Session, root_id: int, owner_id: int) -> List[int]:
    """
    Returns ALL descendant folder IDs (children, grandchildren, etc.) of root_id.
    Does NOT include root_id itself.
    """
    descendants: list[int] = []
    frontier: list[int] = [root_id]

    while frontier:
        child_rows = (
            db.query(Folder.id)
            .filter(
                Folder.owner_id == owner_id,
                Folder.parent_id.in_(frontier),
            )
            .all()
        )
        child_ids = [r[0] for r in child_rows]
        if not child_ids:
            break

        descendants.extend(child_ids)
        frontier = child_ids

    return descendants



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


@router.delete("/{folder_id}/delete-tree")
def delete_folder_tree(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        # Ensure folder exists & owned
        root = (
            db.query(Folder)
            .filter(Folder.id == folder_id, Folder.owner_id == current_user.id)
            .first()
        )
        if not root:
            raise HTTPException(status_code=404, detail="Folder not found")

        # 1) Collect ALL folder ids in subtree (including root)
        stack = [folder_id]
        folder_ids: list[int] = []

        while stack:
            fid = stack.pop()
            folder_ids.append(fid)

            child_ids = [
                r[0]
                for r in db.query(Folder.id)
                .filter(Folder.parent_id == fid, Folder.owner_id == current_user.id)
                .all()
            ]
            stack.extend(child_ids)

        # 2) Collect ALL files in subtree folders (INCLUDING ROOT FOLDER FILES)
        file_ids = [
            r[0]
            for r in db.query(FileModel.id)
            .filter(FileModel.owner_id == current_user.id)
            .filter(FileModel.folder_id.in_(folder_ids))
            .all()
        ]

        deleted_files = len(file_ids)
        deleted_folders = 0

        # 3) Delete file dependencies first
        if file_ids:
            version_ids = [
                r[0]
                for r in db.query(FileVersion.id)
                .filter(FileVersion.file_id.in_(file_ids))
                .all()
            ]

            if version_ids:
                chunk_ids = [
                    r[0]
                    for r in db.query(Chunk.id)
                    .filter(Chunk.file_version_id.in_(version_ids))
                    .all()
                ]

                if chunk_ids:
                    db.query(ChunkLocation).filter(
                        ChunkLocation.chunk_id.in_(chunk_ids)
                    ).delete(synchronize_session=False)

                    db.query(Chunk).filter(
                        Chunk.id.in_(chunk_ids)
                    ).delete(synchronize_session=False)

                db.query(FileVersion).filter(
                    FileVersion.id.in_(version_ids)
                ).delete(synchronize_session=False)

            # If you have file shares/collaborators table, delete those too:
            # db.query(FileShare).filter(FileShare.file_id.in_(file_ids)).delete(synchronize_session=False)

            # 4) Delete files
            db.query(FileModel).filter(
                FileModel.id.in_(file_ids),
                FileModel.owner_id == current_user.id,
            ).delete(synchronize_session=False)

            # ✅ Force DB to apply deletions before folders are removed
            db.flush()

        # 5) Delete folders bottom-up (children first)
        for fid in reversed(folder_ids):
            db.query(Folder).filter(
                Folder.id == fid,
                Folder.owner_id == current_user.id,
            ).delete(synchronize_session=False)
            deleted_folders += 1

        db.commit()

        return {
            "deleted_files": deleted_files,
            "deleted_folders": deleted_folders,
        }

    except SQLAlchemyError as e:
        db.rollback()
        msg = str(e.orig) if hasattr(e, "orig") else str(e)
        raise HTTPException(status_code=500, detail=f"Delete failed: {msg}")


@router.delete("/{folder_id}/delete-all-items", response_model=BulkDeleteResult)
def delete_all_items_in_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owner_id = current_user.id

    root = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.owner_id == owner_id)
        .first()
    )
    if not root:
        raise HTTPException(status_code=404, detail="Folder not found")

    descendant_ids = get_descendant_folder_ids(db, folder_id, owner_id)
    folder_ids_for_files = [folder_id] + descendant_ids

    deleted_files_count = (
        db.query(FileModel.id)
        .filter(
            FileModel.owner_id == owner_id,
            FileModel.folder_id.in_(folder_ids_for_files),
        )
        .count()
    )

    db.execute(
        delete(FileModel).where(
            FileModel.owner_id == owner_id,
            FileModel.folder_id.in_(folder_ids_for_files),
        )
    )

    deleted_folders_count = 0
    remaining = set(descendant_ids)

    Child = aliased(Folder)

    while remaining:
        remaining_list = list(remaining)

        # leaf folders: no child folder whose parent_id is this folder
        leaf_ids = [
            r[0]
            for r in (
                db.query(Folder.id)
                .filter(
                    Folder.owner_id == owner_id,
                    Folder.id.in_(remaining_list),
                    ~exists().where(
                        (Child.owner_id == owner_id)
                        & (Child.parent_id == Folder.id)
                        & (Child.id.in_(remaining_list))
                    ),
                )
                .all()
            )
        ]

        if not leaf_ids:
            # should never happen if remaining truly forms a tree,
            # but prevents infinite loop if data is corrupted
            break

        db.execute(
            delete(Folder).where(
                Folder.owner_id == owner_id,
                Folder.id.in_(leaf_ids),
            )
        )

        deleted_folders_count += len(leaf_ids)
        remaining.difference_update(leaf_ids)

    db.commit()

    return BulkDeleteResult(
        deleted_files=deleted_files_count,
        deleted_folders=deleted_folders_count,
    )


@router.delete("/delete-all-items/root", response_model=BulkDeleteResult)
def delete_all_items_in_root(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owner_id = current_user.id

    # 1) delete root files (folder_id NULL)
    root_file_ids = (
        db.query(FileModel.id)
        .filter(FileModel.owner_id == owner_id, FileModel.folder_id.is_(None))
        .all()
    )
    deleted_root_files = len(root_file_ids)

    db.execute(
        delete(FileModel).where(
            FileModel.owner_id == owner_id,
            FileModel.folder_id.is_(None),
        )
    )

    # 2) get root folders
    root_folder_rows = (
        db.query(Folder.id)
        .filter(Folder.owner_id == owner_id, Folder.parent_id.is_(None))
        .all()
    )
    root_folder_ids = [r[0] for r in root_folder_rows]

    # 3) collect ALL descendants for all root folders
    folder_ids_to_delete: set[int] = set(root_folder_ids)
    for rid in root_folder_ids:
        folder_ids_to_delete.update(get_descendant_folder_ids(db, rid, owner_id))

    folder_ids_list = list(folder_ids_to_delete)
    deleted_folders_count = len(folder_ids_list)

    # 4) delete ALL files in ANY of those folders
    deleted_files_in_folders = 0
    if folder_ids_list:
        files_in_folders = (
            db.query(FileModel.id)
            .filter(
                FileModel.owner_id == owner_id,
                FileModel.folder_id.in_(folder_ids_list),
            )
            .all()
        )
        deleted_files_in_folders = len(files_in_folders)

        db.execute(
            delete(FileModel).where(
                FileModel.owner_id == owner_id,
                FileModel.folder_id.in_(folder_ids_list),
            )
        )

        # 5) delete folders (now safe because ALL descendants are included)
        db.execute(
            delete(Folder).where(
                Folder.owner_id == owner_id,
                Folder.id.in_(folder_ids_list),
            )
        )

    db.commit()

    return BulkDeleteResult(
        deleted_files=deleted_root_files + deleted_files_in_folders,
        deleted_folders=deleted_folders_count,
    )