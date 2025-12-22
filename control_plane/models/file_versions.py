from sqlalchemy import (
    Column,
    Integer,
    DateTime,
    ForeignKey,
    BigInteger,
    func,
)
from sqlalchemy.orm import relationship

from control_plane.db.base import Base


class FileVersion(Base):
    __tablename__ = "file_versions"

    id = Column(Integer, primary_key=True, index=True)

    file_id = Column(
        Integer,
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version_number = Column(Integer, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    file = relationship("File", back_populates="versions")
    chunks = relationship(
        "Chunk",
        back_populates="file_version",
        cascade="all, delete-orphan",
        order_by="Chunk.index",
    )
