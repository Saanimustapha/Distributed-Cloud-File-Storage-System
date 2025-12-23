# app/api/routes/files.py

from typing import Optional

from fastapi import APIRouter, Depends, File, UploadFile, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import httpx
import uuid

from control_plane.core.config import settings
from control_plane.db.session import get_db
from control_plane.models.file import File as FileModel
from control_plane.models.user import User
from control_plane.api.routes.auth import get_current_user
from control_plane.schemas.file import FileRead
from control_plane.schemas.file_version import FileVersionRead
from control_plane.schemas.file_upload import FileUploadResponse
# from control_plane.services.storage_client import upload_chunk_to_node  
from control_plane.models.node import Node
from control_plane.models.chunk import Chunk
from control_plane.models.chunk_locations import ChunkLocation
from control_plane.models.file_versions import FileVersion
from control_plane.models.file_permission import FilePermission
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




@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    version: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Validate file ownership
    db_file = (
        db.query(FileModel)
        .filter(
            FileModel.id == file_id,
            FileModel.owner_id == current_user.id,
        )
        .first()
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
    return (
        db.query(FileVersion)
        .join(FileModel)
        .filter(
            FileModel.id == file_id,
            FileModel.owner_id == current_user.id,
        )
        .order_by(FileVersion.version_number.desc())
        .all()
    )
