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
# from control_plane.services.storage_client import upload_chunk_to_node  
from control_plane.models.node import Node
from control_plane.models.chunk import Chunk
from control_plane.models.chunk_locations import ChunkLocation
from control_plane.services.storage_client import (
    select_nodes_for_chunk_consistent,
    replicate_chunk,
)

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=FileRead)
def upload_file_chunked(
    file: UploadFile = File(...),
    folder_id: Optional[int] = Query(
        default=None,
        description="Optional folder id to associate this file with",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Phase 4 upload with consistent hashing:

    - Create File row (size 0 initially).
    - Read input file in fixed-size chunks (CHUNK_SIZE_BYTES).
    - For each chunk:
      - Generate chunk_id (UUID string).
      - Use consistent hashing on chunk_id to select replication nodes.
      - Upload to those nodes & record Chunk + ChunkLocation.
    - Update total file size.
    """
    chunk_size = settings.CHUNK_SIZE_BYTES

    content_type = file.content_type or "application/octet-stream"
    db_file = FileModel(
        name=file.filename or "unnamed",
        size_bytes=0,
        content_type=content_type,
        owner_id=current_user.id,
        folder_id=folder_id,
        node_id=None,
        chunk_id=None,
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    total_size = 0
    index = 0

    while True:
        chunk_data = file.file.read(chunk_size)
        if not chunk_data:
            break

        total_size += len(chunk_data)

        # Generate a stable ID for this chunk
        chunk_id = str(uuid.uuid4())

        # Consistent hashing: which nodes should store this chunk?
        nodes = select_nodes_for_chunk_consistent(chunk_id=chunk_id, db=db)

        # Upload & record metadata
        replicate_chunk(
            db=db,
            file_id=db_file.id,
            index=index,
            chunk_id=chunk_id,
            data=chunk_data,
            nodes=nodes,
        )

        index += 1

    if index == 0:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty",
        )

    db_file.size_bytes = total_size
    db.commit()
    db.refresh(db_file)

    return db_file





@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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

    chunks = (
        db.query(Chunk)
        .filter(Chunk.file_id == db_file.id)
        .order_by(Chunk.index.asc())
        .all()
    )
    if not chunks:
        raise HTTPException(
            status_code=500,
            detail="No chunks found for file",
        )

    def iter_file_bytes():
        for chunk in chunks:
            # find all online replicas for this chunk
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

            success = False

            for loc in locations:
                node = loc.node
                url = f"{node.base_url.rstrip('/')}/chunks/{chunk.id}"

                try:
                    with httpx.stream("GET", url, timeout=30.0) as resp:
                        if resp.status_code != 200:
                            # try next replica
                            continue

                        for data in resp.iter_bytes():
                            if data:
                                yield data

                        success = True
                        break

                except httpx.RequestError:
                    # try next replica
                    continue

            if not success:
                raise HTTPException(
                    status_code=502,
                    detail=f"All replicas failed for chunk {chunk.index}",
                )

    media_type = db_file.content_type or "application/octet-stream"
    headers = {
        "Content-Disposition": f'attachment; filename="{db_file.name}"'
    }

    return StreamingResponse(iter_file_bytes(), media_type=media_type, headers=headers)
