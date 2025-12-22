import os
from pathlib import Path
import mimetypes

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import FileResponse

import aiofiles

app = FastAPI(title="Storage Node")

CHUNK_DIR = Path(os.getenv("CHUNK_DIR", "/data/chunks"))
CHUNK_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.put("/chunks/{chunk_id}", status_code=status.HTTP_201_CREATED)
async def put_chunk(chunk_id: str, request: Request):
    """
    Store raw request body as a chunk.
    """
    dest = CHUNK_DIR / chunk_id

    # Ensure parent dir exists (for future subdirs)
    dest.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(dest, "wb") as f:
        async for chunk in request.stream():
            await f.write(chunk)

    return {"chunk_id": chunk_id}


@app.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: str):
    """
    Stream the stored chunk back.
    """
    path = CHUNK_DIR / chunk_id
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chunk not found")

    # Guess MIME type from file extension (pdf, docx, jpg, png, mp4, etc.)
    mime_type, _ = mimetypes.guess_type(str(path))
    # Fallback to generic binary stream if unknown
    media_type = mime_type or "application/octet-stream"

    return FileResponse(path, media_type=media_type)
