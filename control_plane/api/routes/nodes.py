from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from control_plane.db.session import get_db
from control_plane.models.node import Node
from control_plane.schemas.node import NodeCreate, NodeRead
from control_plane.api.routes.auth import get_current_user  # to require auth
from control_plane.models.user import User

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.post("/create", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
def register_node(
    payload: NodeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # For now, let any logged-in user register. Later you can restrict to admins.
    existing = db.query(Node).filter(Node.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Node with that name already exists")

    node = Node(
        name=payload.name,
        base_url=str(payload.base_url),
        is_online=payload.is_online,
        capacity_bytes=payload.capacity_bytes,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@router.get("/all", response_model=List[NodeRead])
def list_nodes(
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page_size = 10
    skip = (page - 1) * page_size

    nodes = (
        db.query(Node)
        .order_by(Node.id.asc())
        .offset(skip)
        .limit(page_size)
        .all()
    )

    return nodes


@router.delete("/delete/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(
    node_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    node = db.query(Node).filter(Node.id == node_id).first()

    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found",
        )

    db.delete(node)
    db.commit()

    return None

