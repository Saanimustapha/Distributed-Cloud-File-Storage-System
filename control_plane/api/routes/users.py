from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from control_plane.db.session import get_db
from control_plane.api.routes.auth import get_current_user
from control_plane.models.user import User
from control_plane.schemas.user import UserRead

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/search", response_model=List[UserRead])
def search_users(
    email: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None, description="Search by email (partial)"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Find users for sharing:
    - /users/search?email=exact@email.com  (exact match)
    - /users/search?query=gmail           (partial match)
    Returns list so UI can show suggestions.
    """

    q = db.query(User)

    if email:
        q = q.filter(User.email.ilike(email))
    elif query:
        q = q.filter(User.email.ilike(f"%{query}%"))
    else:
        raise HTTPException(status_code=400, detail="Provide 'email' or 'query'")

    # Optional: don't return yourself in search results
    q = q.filter(User.id != current_user.id)

    return q.order_by(User.email.asc()).limit(limit).all()


