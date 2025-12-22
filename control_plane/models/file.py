from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    BigInteger,
    func,
)
from sqlalchemy.orm import relationship

from control_plane.db.base import Base


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    content_type = Column(String, nullable=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    folder_id = Column(Integer, ForeignKey("folders.id"), nullable=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True)
    chunk_id = Column(String, nullable=True, index=True)
    # node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)

    # The ID used by the storage node to store the data
    # chunk_id = Column(String, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner = relationship("User", backref="files")
    folder = relationship("Folder", backref="files")
    node = relationship("Node", backref="files", foreign_keys=[node_id])

    chunks = relationship(
        "Chunk",
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="Chunk.index",
    )
