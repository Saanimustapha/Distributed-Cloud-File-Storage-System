from sqlalchemy import (
    Column,
    Integer,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from control_plane.db.base import Base


class ChunkLocation(Base):
    __tablename__ = "chunk_locations"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(String, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chunk = relationship("Chunk", back_populates="locations")
    node = relationship("Node", back_populates="chunk_locations")

    __table_args__ = (
        UniqueConstraint("chunk_id", "node_id", name="uq_chunk_node"),
    )
