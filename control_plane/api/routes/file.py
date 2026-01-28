# app/api/routes/files.py

from typing import Optional, List

from fastapi import APIRouter, Depends, File, UploadFile, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
import httpx
import uuid
import mimetypes


from control_plane.core.config import settings
from control_plane.db.session import get_db
from control_plane.models.file import File as FileModel
from control_plane.models.user import User
from control_plane.api.routes.auth import get_current_user
from control_plane.schemas.file import FileRead
from control_plane.schemas.file_permission import FileShareRead
from control_plane.schemas.file_version import FileVersionRead
from control_plane.schemas.file_upload import FileUploadResponse
from control_plane.schemas.file_permission import ShareFileRequest
# from control_plane.services.storage_client import upload_chunk_to_node  
from control_plane.models.node import Node
from control_plane.models.chunk import Chunk
from control_plane.models.chunk_locations import ChunkLocation
from control_plane.models.file_versions import FileVersion
from control_plane.models.file_permission import FilePermission
from control_plane.schemas.file_list import FileListItem
from control_plane.services.permissions import get_file_for_user
from control_plane.models.notification import Notification
from control_plane.schemas.file_rename import FileRename
from control_plane.services.web_socket_manager import ws_manager
from control_plane.services.storage_client import (
    select_nodes_for_chunk_consistent,
    replicate_chunk,
)

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=FileUploadResponse)
def upload_file(
    file: UploadFile = File(...),
    folder_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Find or create File
    db_file = (
        db.query(FileModel)
        .filter(
            FileModel.name == file.filename,
            FileModel.owner_id == current_user.id,
            FileModel.folder_id == folder_id,
        )
        .first()
    )

    if not db_file:
        db_file = FileModel(
            name=file.filename,
            owner_id=current_user.id,
            folder_id=folder_id,
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)

        owner_permission = FilePermission(
        file_id=db_file.id,
        user_id=current_user.id,
        role="owner",
        )
        
        db.add(owner_permission)
        db.commit()

    get_file_for_user(
        db=db,
        file_id=db_file.id,
        user_id=current_user.id,
        required_role="write",
    )

    # 2. Determine next version number
    latest_version = (
        db.query(FileVersion)
        .filter(FileVersion.file_id == db_file.id)
        .order_by(FileVersion.version_number.desc())
        .first()
    )

    next_version = 1 if not latest_version else latest_version.version_number + 1

    # 3. Create FileVersion
    version = FileVersion(
        file_id=db_file.id,
        version_number=next_version,
        size_bytes=0,
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    # 4. Chunk + replicate
    total_size = 0
    index = 0
    chunk_size = settings.CHUNK_SIZE_BYTES

    while True:
        data = file.file.read(chunk_size)
        if not data:
            break

        chunk_id = str(uuid.uuid4())
        nodes = select_nodes_for_chunk_consistent(chunk_id, db)

        replicate_chunk(
            db=db,
            file_version_id=version.id,
            index=index,
            chunk_id=chunk_id,
            data=data,
            nodes=nodes,
        )

        total_size += len(data)
        index += 1

    version.size_bytes = total_size
    db.commit()

    return {
    "file": db_file,
    "version": version,
    }




@router.post("/{file_id}/versions", response_model=FileVersionRead, status_code=status.HTTP_201_CREATED)
def upload_new_version(
    file_id: int,
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a new version for an existing file.
    - Requires WRITE permission (owner/write).
    - Creates a new FileVersion.
    - Splits the uploaded content into chunks.
    - Stores each chunk on R nodes using consistent hashing + replication.
    """

    # 1) Permission check: must be allowed to edit this file
    file_obj: FileModel = get_file_for_user(
        db=db,
        file_id=file_id,
        user_id=current_user.id,
        required_role="write",
    )

    # 2) Determine next version number for this file
    latest_version = (
        db.query(FileVersion)
        .filter(FileVersion.file_id == file_obj.id)
        .order_by(FileVersion.version_number.desc())
        .first()
    )
    next_version = 1 if not latest_version else latest_version.version_number + 1

    # 3) Create FileVersion row (size filled after upload)
    version = FileVersion(
        file_id=file_obj.id,
        version_number=next_version,
        size_bytes=0,
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    # 4) Chunk + replicate
    total_size = 0
    index = 0
    chunk_size = settings.CHUNK_SIZE_BYTES

    while True:
        data = upload.file.read(chunk_size)
        if not data:
            break

        chunk_id = str(uuid.uuid4())

        # Consistent hashing decides primary+replicas for THIS chunk_id
        nodes = select_nodes_for_chunk_consistent(chunk_id=chunk_id, db=db)

        replicate_chunk(
            db=db,
            file_version_id=version.id,
            index=index,
            chunk_id=chunk_id,
            data=data,
            nodes=nodes,
        )

        total_size += len(data)
        index += 1

    if index == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # 5) Update version size
    version.size_bytes = total_size
    db.commit()
    db.refresh(version)

    return version



@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    version: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Validate file ownership
    # db_file = (
    #     db.query(FileModel)
    #     .filter(
    #         FileModel.id == file_id,
    #         FileModel.owner_id == current_user.id,
    #     )
    #     .first()
    # )
    db_file = get_file_for_user(
    db=db,
    file_id=file_id,
    user_id=current_user.id,
    required_role="read",
    )

    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")

    # 2. Select file version
    if version is None:
        # latest version (versions are ordered desc)
        if not db_file.versions:
            raise HTTPException(status_code=404, detail="No versions found for file")
        file_version = db_file.versions[0]
    else:
        file_version = (
            db.query(FileVersion)
            .filter(
                FileVersion.file_id == db_file.id,
                FileVersion.version_number == version,
            )
            .first()
        )

    if not file_version:
        raise HTTPException(status_code=404, detail="Version not found")

    # 3. Load chunks in correct order
    chunks = (
        db.query(Chunk)
        .filter(Chunk.file_version_id == file_version.id)
        .order_by(Chunk.index.asc())
        .all()
    )

    if not chunks:
        raise HTTPException(
            status_code=500,
            detail="No chunks found for this file version",
        )

    # 4. Stream chunks sequentially with replica failover
    def stream_file_bytes():
        for chunk in chunks:
            # Fetch all ONLINE replicas for this chunk
            locations = (
                db.query(ChunkLocation)
                .join(Node, ChunkLocation.node_id == Node.id)
                .filter(
                    ChunkLocation.chunk_id == chunk.id,
                    Node.is_online.is_(True),
                )
                .all()
            )

            if not locations:
                raise HTTPException(
                    status_code=503,
                    detail=f"No online replicas available for chunk {chunk.index}",
                )

            chunk_served = False

            # Try replicas in order
            for location in locations:
                node = location.node
                url = f"{node.base_url.rstrip('/')}/chunks/{chunk.id}"

                try:
                    with httpx.stream("GET", url, timeout=30.0) as response:
                        if response.status_code != 200:
                            continue

                        for data in response.iter_bytes():
                            if data:
                                yield data

                        chunk_served = True
                        break

                except httpx.RequestError:
                    # Try next replica
                    continue

            if not chunk_served:
                raise HTTPException(
                    status_code=502,
                    detail=f"All replicas failed for chunk {chunk.index}",
                )

    # 5. Return streaming response
    media_type = "application/octet-stream"
    headers = {
        "Content-Disposition": f'attachment; filename="{db_file.name}"'
    }

    return StreamingResponse(
        stream_file_bytes(),
        media_type=media_type,
        headers=headers,
    )



@router.get("/{file_id}/versions", response_model=list[FileVersionRead])
def list_versions(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ✅ Permission check first (shared users with read/write/owner should pass)
    get_file_for_user(
        db=db,
        file_id=file_id,
        user_id=current_user.id,
        required_role="read",
    )

    # ✅ Then return versions (no owner_id filter needed)
    return (
        db.query(FileVersion)
        .filter(FileVersion.file_id == file_id)
        .order_by(FileVersion.version_number.desc())
        .all()
    )


@router.post("/{file_id}/share")
async def share_file(
    file_id: int,
    payload: ShareFileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Owner check
    get_file_for_user(
        db=db,
        file_id=file_id,
        user_id=current_user.id,
        required_role="owner",
    )

    permission = (
        db.query(FilePermission)
        .filter(
            FilePermission.file_id == file_id,
            FilePermission.user_id == payload.user_id,
        )
        .first()
    )

    if permission:
        permission.role = payload.role
    else:
        permission = FilePermission(
            file_id=file_id,
            user_id=payload.user_id,
            role=payload.role,
        )
        db.add(permission)

    db.commit()

    # create notification row for recipient
    note = Notification(
        user_id=payload.user_id,
        type="file_shared",
        message=f"A file was shared with you from {current_user.email}",
        file_id=file_id,
        actor_user_id=current_user.id,
        is_read=False,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    # push realtime
    await ws_manager.send_to_user(payload.user_id, {
        "event": "notification",
        "notification": {
            "id": note.id,
            "type": note.type,
            "message": note.message,
            "file_id": note.file_id,
            "actor_user_id": note.actor_user_id,
            "is_read": note.is_read,
            "created_at": note.created_at,
        }
    })

    return {"message": "File shared successfully"}


@router.get("/{file_id}/permissions")
def list_permissions(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_file_for_user(
        db=db,
        file_id=file_id,
        user_id=current_user.id,
        required_role="owner",
    )

    return (
        db.query(FilePermission)
        .filter(FilePermission.file_id == file_id)
        .all()
    )


@router.delete("/{file_id}/delete", status_code=status.HTTP_200_OK)
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1) File must exist
    file_obj = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")

    # 2) Only OWNER can delete
    perm = (
        db.query(FilePermission)
        .filter(
            FilePermission.file_id == file_id,
            FilePermission.user_id == current_user.id,
        )
        .first()
    )

    if not perm or perm.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the file owner can delete this file",
        )

    # 3) Delete the file record
    # IMPORTANT:
    # - If you set cascading correctly on relationships / foreign keys,
    #   versions/chunks/locations/permissions will delete automatically.
    db.delete(file_obj)
    db.commit()

    return {"message": "File deleted successfully"}



@router.get("/all", response_model=List[FileListItem])
def list_my_files(
    folder_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List files owned by the current user in a folder.
    If folder_id is null -> list files in root (folder_id IS NULL).
    Includes latest version metadata for UI.
    """

    # Subquery to get the max version_number for each file_id
    latest_vn_sq = (
        db.query(
            FileVersion.file_id.label("file_id"),
            func.max(FileVersion.version_number).label("max_vn"),
        )
        .group_by(FileVersion.file_id)
        .subquery()
    )

    # Join file_versions to get metadata for that max version per file
    latest_version_sq = (
        db.query(
            FileVersion.file_id.label("file_id"),
            FileVersion.version_number.label("latest_version_number"),
            FileVersion.size_bytes.label("latest_version_size_bytes"),
            FileVersion.created_at.label("latest_version_created_at"),
        )
        .join(
            latest_vn_sq,
            and_(
                FileVersion.file_id == latest_vn_sq.c.file_id,
                FileVersion.version_number == latest_vn_sq.c.max_vn,
            ),
        )
        .subquery()
    )

    q = (
        db.query(
            FileModel.id,
            FileModel.name,
            FileModel.folder_id,
            FileModel.owner_id,
            FileModel.created_at,
            FileModel.updated_at,
            latest_version_sq.c.latest_version_number,
            latest_version_sq.c.latest_version_size_bytes,
            latest_version_sq.c.latest_version_created_at,
        )
        .outerjoin(latest_version_sq, latest_version_sq.c.file_id == FileModel.id)
        .filter(FileModel.owner_id == current_user.id)
    )

    if folder_id is None:
        q = q.filter(FileModel.folder_id.is_(None))
    else:
        q = q.filter(FileModel.folder_id == folder_id)

    rows = q.order_by(FileModel.updated_at.desc()).all()

    # Convert SQLAlchemy row tuples to dicts
    return [
        {
            "id": r.id,
            "name": r.name,
            "folder_id": r.folder_id,
            "owner_id": r.owner_id,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "latest_version_number": r.latest_version_number,
            "latest_version_size_bytes": r.latest_version_size_bytes,
            "latest_version_created_at": r.latest_version_created_at,
        }
        for r in rows
    ]


@router.get("/shared", response_model=List[FileListItem])
def list_shared_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List files shared with the current user (has permission) but not owned.
    Includes latest version metadata for UI.
    """

    latest_vn_sq = (
        db.query(
            FileVersion.file_id.label("file_id"),
            func.max(FileVersion.version_number).label("max_vn"),
        )
        .group_by(FileVersion.file_id)
        .subquery()
    )

    latest_version_sq = (
        db.query(
            FileVersion.file_id.label("file_id"),
            FileVersion.version_number.label("latest_version_number"),
            FileVersion.size_bytes.label("latest_version_size_bytes"),
            FileVersion.created_at.label("latest_version_created_at"),
        )
        .join(
            latest_vn_sq,
            and_(
                FileVersion.file_id == latest_vn_sq.c.file_id,
                FileVersion.version_number == latest_vn_sq.c.max_vn,
            ),
        )
        .subquery()
    )

    q = (
        db.query(
            FileModel.id,
            FileModel.name,
            FileModel.folder_id,
            FileModel.owner_id,
            FileModel.created_at,
            FileModel.updated_at,
            latest_version_sq.c.latest_version_number,
            latest_version_sq.c.latest_version_size_bytes,
            latest_version_sq.c.latest_version_created_at,
            FilePermission.role.label("my_role"),  
        )
        .join(FilePermission, FilePermission.file_id == FileModel.id)
        .outerjoin(latest_version_sq, latest_version_sq.c.file_id == FileModel.id)
        .filter(FilePermission.user_id == current_user.id)
        .filter(FileModel.owner_id != current_user.id)
    )

    rows = q.order_by(FileModel.updated_at.desc()).all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "folder_id": r.folder_id,
            "owner_id": r.owner_id,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "latest_version_number": r.latest_version_number,
            "latest_version_size_bytes": r.latest_version_size_bytes,
            "latest_version_created_at": r.latest_version_created_at,
            "my_role": r.my_role, 
        }
        for r in rows
    ]


@router.get("/shared-by-me", response_model=List[FileListItem])
def list_files_shared_by_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List files owned by current user that have been shared with at least one other user.
    """

    # Latest version per file
    latest_vn_sq = (
        db.query(
            FileVersion.file_id.label("file_id"),
            func.max(FileVersion.version_number).label("max_vn"),
        )
        .group_by(FileVersion.file_id)
        .subquery()
    )

    latest_version_sq = (
        db.query(
            FileVersion.file_id.label("file_id"),
            FileVersion.version_number.label("latest_version_number"),
            FileVersion.size_bytes.label("latest_version_size_bytes"),
            FileVersion.created_at.label("latest_version_created_at"),
        )
        .join(
            latest_vn_sq,
            and_(
                FileVersion.file_id == latest_vn_sq.c.file_id,
                FileVersion.version_number == latest_vn_sq.c.max_vn,
            ),
        )
        .subquery()
    )

    # Count collaborators (exclude owner)
    collaborators_sq = (
        db.query(
            FilePermission.file_id.label("file_id"),
            func.count(FilePermission.user_id).label("collaborator_count"),
        )
        .join(FileModel, FileModel.id == FilePermission.file_id)
        .filter(FileModel.owner_id == current_user.id)
        .filter(FilePermission.user_id != current_user.id)
        .group_by(FilePermission.file_id)
        .subquery()
    )

    q = (
        db.query(
            FileModel.id,
            FileModel.name,
            FileModel.folder_id,
            FileModel.owner_id,
            FileModel.created_at,
            FileModel.updated_at,
            latest_version_sq.c.latest_version_number,
            latest_version_sq.c.latest_version_size_bytes,
            latest_version_sq.c.latest_version_created_at,
            collaborators_sq.c.collaborator_count,
        )
        .outerjoin(latest_version_sq, latest_version_sq.c.file_id == FileModel.id)
        .join(collaborators_sq, collaborators_sq.c.file_id == FileModel.id)  # ensures shared with others
        .filter(FileModel.owner_id == current_user.id)
        .order_by(FileModel.updated_at.desc())
    )

    rows = q.all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "folder_id": r.folder_id,
            "owner_id": r.owner_id,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "latest_version_number": r.latest_version_number,
            "latest_version_size_bytes": r.latest_version_size_bytes,
            "latest_version_created_at": r.latest_version_created_at,
            "collaborator_count": r.collaborator_count,
        }
        for r in rows
    ]


@router.get("/{file_id}/shares-by-me", response_model=List[FileShareRead])
def list_file_shares(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List everyone this file has been shared with (and their roles).
    Owner-only.
    """
    # Owner check
    get_file_for_user(
        db=db,
        file_id=file_id,
        user_id=current_user.id,
        required_role="owner",
    )

    rows = (
        db.query(FilePermission, User)
        .join(User, User.id == FilePermission.user_id)
        .filter(FilePermission.file_id == file_id)
        .filter(User.id != current_user.id)  # exclude owner from list (optional)
        .order_by(User.email.asc())
        .all()
    )

    return [
        {
            "user_id": user.id,
            "email": user.email,
            "role": perm.role,
            "shared_at": perm.created_at,
        }
        for perm, user in rows
    ]


@router.get("/{file_id}/view")
def view_file(
    file_id: int,
    version: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_file = get_file_for_user(
        db=db,
        file_id=file_id,
        user_id=current_user.id,
        required_role="read",
    )

    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")

    # Select version
    if version is None:
        if not db_file.versions:
            raise HTTPException(status_code=404, detail="No versions found for file")
        file_version = db_file.versions[0]
    else:
        file_version = (
            db.query(FileVersion)
            .filter(
                FileVersion.file_id == db_file.id,
                FileVersion.version_number == version,
            )
            .first()
        )
        if not file_version:
            raise HTTPException(status_code=404, detail="Version not found")

    chunks = (
        db.query(Chunk)
        .filter(Chunk.file_version_id == file_version.id)
        .order_by(Chunk.index.asc())
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=500, detail="No chunks found for this file version")

    def stream_file_bytes():
        for chunk in chunks:
            locations = (
                db.query(ChunkLocation)
                .join(Node, ChunkLocation.node_id == Node.id)
                .filter(
                    ChunkLocation.chunk_id == chunk.id,
                    Node.is_online.is_(True),
                )
                .all()
            )
            if not locations:
                raise HTTPException(status_code=503, detail=f"No online replicas for chunk {chunk.index}")

            served = False
            for location in locations:
                node = location.node
                url = f"{node.base_url.rstrip('/')}/chunks/{chunk.id}"

                try:
                    with httpx.stream("GET", url, timeout=30.0) as response:
                        if response.status_code != 200:
                            continue

                        for data in response.iter_bytes():
                            if data:
                                yield data

                        served = True
                        break

                except httpx.RequestError:
                    continue

            if not served:
                raise HTTPException(status_code=502, detail=f"All replicas failed for chunk {chunk.index}")

    # ✅ Guess correct content type from filename
    content_type, _ = mimetypes.guess_type(db_file.name)
    media_type = content_type or "application/octet-stream"

    headers = {
        # ✅ INLINE so browsers can preview PDFs/images/etc.
        "Content-Disposition": f'inline; filename="{db_file.name}"'
    }

    return StreamingResponse(
        stream_file_bytes(),
        media_type=media_type,
        headers=headers,
    )

@router.patch("/{file_id}/rename", response_model=FileRead, status_code=status.HTTP_200_OK)
def rename_file(
    file_id: int,
    payload: FileRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="File name cannot be empty")

    # Must have WRITE permission (owner/write)
    file_obj: FileModel = get_file_for_user(
        db=db,
        file_id=file_id,
        user_id=current_user.id,
        required_role="write",
    )

    # No-op
    if file_obj.name == new_name:
        return file_obj

    # Prevent duplicate names in same folder for the OWNER
    # (since name uniqueness is defined by owner_id + folder_id + name in your upload logic)
    existing = (
        db.query(FileModel)
        .filter(
            FileModel.owner_id == file_obj.owner_id,
            FileModel.folder_id == file_obj.folder_id,
            FileModel.name == new_name,
            FileModel.id != file_obj.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="A file with that name already exists in this folder",
        )

    file_obj.name = new_name
    db.commit()
    db.refresh(file_obj)
    return file_obj
