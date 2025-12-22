from sqlalchemy import Column, Integer, String, Boolean, DateTime, func, BigInteger
from control_plane.db.base import Base
from sqlalchemy.orm import relationship


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    base_url = Column(String, nullable=False)  # e.g. http://10.0.0.5:8000 or http://localhost:9001
    is_online = Column(Boolean, nullable=False, server_default="true")
    capacity_bytes = Column(BigInteger, nullable=True)  # optional, for future
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chunk_locations = relationship(
        "ChunkLocation",
        back_populates="node",
        cascade="all, delete-orphan",
    )
