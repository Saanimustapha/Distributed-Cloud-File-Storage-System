from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from control_plane.db.base import Base

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # e.g. "file_shared"
    type = Column(String, nullable=False)

    # message shown in UI
    message = Column(String, nullable=False)

    # optional metadata for routing
    file_id = Column(Integer, nullable=True)
    actor_user_id = Column(Integer, nullable=True)

    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
