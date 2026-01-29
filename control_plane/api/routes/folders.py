from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
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


def get_descendant_folder_ids(db: Session, root_folder_id: int, owner_id: int) -> list[int]:
    """
    Returns ALL descendant folder ids (any depth), NOT including root_folder_id.
    """
    result: list[int] = []
    stack = [root_folder_id]

    while stack:
        parent = stack.pop()
        children = (
            db.query(Folder.id)
            .filter(Folder.parent_id == parent, Folder.owner_id == owner_id)
            .all()
        )
        child_ids = [c[0] for c in children]
        result.extend(child_ids)
        stack.extend(child_ids)

    return result



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
    root = (
        db.query(Folder)
        .filter(Folder.id == folder_id, Folder.owner_id == current_user.id)
        .first()
    )
    if not root:
        raise HTTPException(status_code=404, detail="Folder not found")

    owner_id = current_user.id

    # 1) collect descendant folders (any depth)
    descendant_ids = get_descendant_folder_ids(db, folder_id, owner_id)

    # include root folder id? NO (we want to keep current folder)
    all_folder_ids = descendant_ids

    # 2) delete files in root folder + descendant folders
    folder_ids_for_files = [folder_id] + descendant_ids

    files_to_delete = (
        db.query(FileModel.id)
        .filter(FileModel.owner_id == owner_id)
        .filter(FileModel.folder_id.in_(folder_ids_for_files))
        .all()
    )
    deleted_files_count = len(files_to_delete)

    db.execute(
        delete(FileModel).where(
            FileModel.owner_id == owner_id,
            FileModel.folder_id.in_(folder_ids_for_files),
        )
    )

    # 3) delete folders bottom-up (deepest first)
    # delete descendants only (not the root folder itself)
    deleted_folders_count = len(descendant_ids)
    if descendant_ids:
        db.execute(
            delete(Folder).where(
                Folder.owner_id == owner_id,
                Folder.id.in_(descendant_ids),
            )
        )

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
        .filter(FileModel.owner_id == owner_id)
        .filter(FileModel.folder_id.is_(None))
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
    root_folders = (
        db.query(Folder.id)
        .filter(Folder.owner_id == owner_id)
        .filter(Folder.parent_id.is_(None))
        .all()
    )
    root_folder_ids = [r[0] for r in root_folders]

    # 3) collect ALL descendant folders for all root folders
    all_descendants: list[int] = []
    for fid in root_folder_ids:
        all_descendants.extend(get_descendant_folder_ids(db, fid, owner_id))

    all_folders_to_delete = root_folder_ids + all_descendants
    deleted_folders_count = len(all_folders_to_delete)

    # 4) delete ALL files in ANY of those folders
    deleted_files_in_folders = 0
    if all_folders_to_delete:
        files_in_folders = (
            db.query(FileModel.id)
            .filter(FileModel.owner_id == owner_id)
            .filter(FileModel.folder_id.in_(all_folders_to_delete))
            .all()
        )
        deleted_files_in_folders = len(files_in_folders)

        db.execute(
            delete(FileModel).where(
                FileModel.owner_id == owner_id,
                FileModel.folder_id.in_(all_folders_to_delete),
            )
        )

        # 5) delete folders (root + descendants)
        db.execute(
            delete(Folder).where(
                Folder.owner_id == owner_id,
                Folder.id.in_(all_folders_to_delete),
            )
        )

    db.commit()

    return BulkDeleteResult(
        deleted_files=deleted_root_files + deleted_files_in_folders,
        deleted_folders=deleted_folders_count,
    )
