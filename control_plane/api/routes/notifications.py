from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from control_plane.db.session import get_db
from control_plane.api.routes.auth import get_current_user
from control_plane.models.user import User
from control_plane.models.notification import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/unread", response_model=list[dict])
def list_unread_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )

    return [
        {
            "id": n.id,
            "type": n.type,
            "message": n.message,
            "file_id": n.file_id,
            "actor_user_id": n.actor_user_id,
            "is_read": n.is_read,
            "created_at": n.created_at,
        }
        for n in rows
    ]


@router.patch("/{notification_id}/read", response_model=dict)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")

    n.is_read = True
    db.commit()
    return {"ok": True}
