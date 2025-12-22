import hashlib
import uuid
from typing import List, Tuple

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from control_plane.core.config import settings
from control_plane.models.node import Node
from control_plane.models.chunk import Chunk
from control_plane.models.chunk_locations import ChunkLocation


def get_online_nodes(db: Session) -> List[Node]:
    nodes = (
        db.query(Node)
        .filter(Node.is_online.is_(True))
        .order_by(Node.id.asc())
        .all()
    )
    if not nodes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No online storage nodes available",
        )
    return nodes

def _hash_key(key: str) -> int:
    # stable 256-bit integer from any string
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)


def build_hash_ring(nodes: List[Node]) -> List[Tuple[int, Node]]:
    """
    Build a simple hash ring: list of (hash, node), sorted by hash.
    """
    ring: List[Tuple[int, Node]] = []
    for node in nodes:
        # you can change the key to use name/host/etc.
        node_key = f"node-{node.id}"
        h = _hash_key(node_key)
        ring.append((h, node))

    ring.sort(key=lambda x: x[0])
    return ring


def select_nodes_for_chunk_consistent(
    chunk_id: str,
    db: Session,
    replication_factor: int | None = None,
) -> List[Node]:
    """
    Given a chunk_id, pick R nodes using consistent hashing:
      - find first node on ring whose hash >= hash(chunk_id)
      - take that node + next R-1 nodes (wrapping around)
    """
    if replication_factor is None:
        replication_factor = settings.REPLICATION_FACTOR

    nodes = get_online_nodes(db)
    ring = build_hash_ring(nodes)

    if len(nodes) <= replication_factor:
        # fewer nodes than replication factor -> use them all
        return nodes

    key_hash = _hash_key(chunk_id)

    # find first node whose hash >= key_hash
    start_idx = 0
    for i, (h, _) in enumerate(ring):
        if h >= key_hash:
            start_idx = i
            break
    else:
        # if none found, wrap to the first node
        start_idx = 0

    # walk ring to pick R distinct nodes
    selected: List[Node] = []
    i = start_idx
    while len(selected) < replication_factor and len(selected) < len(ring):
        node = ring[i][1]
        if node not in selected:
            selected.append(node)
        i = (i + 1) % len(ring)

    return selected


def replicate_chunk(
    db: Session,
    file_version_id: int,
    index: int,
    chunk_id: str,
    data: bytes,
    nodes: List[Node],
    timeout: float = 10.0,
) -> Chunk:
    """
    Upload a single chunk's bytes to all given nodes and create:
      - 1 Chunk row
      - N ChunkLocation rows
    """
    size_bytes = len(data)

    # 1) Create Chunk row
    chunk = Chunk(
        id=chunk_id,
        file_version_id=file_version_id,
        index=index,
        size_bytes=size_bytes,
    )
    db.add(chunk)
    db.flush()  # chunk is now known to the session

    # 2) Upload to each node & create ChunkLocation
    for node in nodes:
        url = f"{node.base_url.rstrip('/')}/chunks/{chunk_id}"

        try:
            resp = httpx.put(url, content=data, timeout=timeout)
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to reach storage node {node.name}: {e}",
            )

        if resp.status_code not in (200, 201):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Node {node.name} returned {resp.status_code}: {resp.text}",
            )

        location = ChunkLocation(
            chunk_id=chunk_id,
            node_id=node.id,
        )
        db.add(location)

    return chunk




# def _choose_node(db: Session) -> Node:
#     """
#     Simple node selection: pick the first online node.
#     Later you can do round-robin / random / weighted, etc.
#     """
#     node = (
#         db.query(Node)
#         .filter(Node.is_online.is_(True))
#         .order_by(Node.id.asc())
#         .first()
#     )
#     if not node:
#         raise HTTPException(
#             status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
#             detail="No online storage nodes available",
#         )
#     return node


# def upload_chunk_to_node(
#     db: Session,
#     data: bytes,
#     node_id: int | None = None,
#     timeout: float = 10.0,
# ) -> tuple[str, Node]:
#     """
#     Pick a node (or use the given node_id), generate a chunk_id,
#     and PUT the bytes to {node.base_url}/chunks/{chunk_id}.

#     Returns: (chunk_id, node)
#     """
#     # 1) Pick node
#     if node_id is not None:
#         node = (
#             db.query(Node)
#             .filter(Node.id == node_id, Node.is_online.is_(True))
#             .first()
#         )
#         if not node:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Node {node_id} not found or offline",
#             )
#     else:
#         node = _choose_node(db)

#     # 2) Generate chunk_id
#     chunk_id = str(uuid.uuid4())

#     # 3) Send PUT to storage node
#     url = f"{node.base_url.rstrip('/')}/chunks/{chunk_id}"

#     try:
#         resp = httpx.put(url, content=data, timeout=timeout)
#     except httpx.RequestError as e:
#         raise HTTPException(
#             status_code=status.HTTP_502_BAD_GATEWAY,
#             detail=f"Failed to reach storage node {node.name}: {e}",
#         )

#     if resp.status_code not in (200, 201):
#         raise HTTPException(
#             status_code=status.HTTP_502_BAD_GATEWAY,
#             detail=f"Node {node.name} returned {resp.status_code}: {resp.text}",
#         )

#     return chunk_id, node
