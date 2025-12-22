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


class Chunk(Base):
    __tablename__ = "chunks"

    # We'll use the storage chunk_id as the primary key (UUID string)
    id = Column(String, primary_key=True, index=True)

    # file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    file_version_id = Column(Integer, ForeignKey("file_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    index = Column(Integer, nullable=False)  # 0,1,2,... order within file
    size_bytes = Column(BigInteger, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    file_version = relationship("FileVersion", back_populates="chunks")
    locations = relationship(
        "ChunkLocation",
        back_populates="chunk",
        cascade="all, delete-orphan",
    )
