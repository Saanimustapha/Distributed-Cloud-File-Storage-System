from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from control_plane.models.file import File as FileModel
from control_plane.models.file_permission import FilePermission


ROLE_HIERARCHY = {
    "read": {"read", "write", "owner"},
    "write": {"write", "owner"},
    "owner": {"owner"},
}


def get_file_for_user(
    *,
    db: Session,
    file_id: int,
    user_id: int,
    required_role: str,
) -> FileModel:
    """
    Fetch file if user has required permission.
    Raises HTTPException if access is denied.
    """
    permission = (
        db.query(FilePermission)
        .filter(
            FilePermission.file_id == file_id,
            FilePermission.user_id == user_id,
        )
        .first()
    )

    if not permission:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this file",
        )

    if permission.role not in ROLE_HIERARCHY[required_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires {required_role} permission",
        )

    file = db.query(FileModel).filter(FileModel.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    return file
