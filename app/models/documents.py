from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Document(Base):
    """An uploaded/received invoice or receipt. Never deleted once booked (bewaarplicht); an unbooked one can be deleted."""

    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint("status IN ('nieuw','herkend','geboekt')", name="ck_document_status"),
        CheckConstraint("source IN ('upload','email')", name="ck_document_source"),
        CheckConstraint("size_bytes > 0", name="ck_document_size"),
        CheckConstraint("length(sha256) = 64", name="ck_document_sha256"),
        CheckConstraint(
            "status <> 'geboekt' OR journal_entry_id IS NOT NULL", name="ck_document_booked_link"
        ),
        Index("uq_document_sha256", "sha256", unique=True),
        Index("ix_document_status", "status"),
        Index("ix_document_received_at", "received_at"),
        Index("ix_document_journal_entry_id", "journal_entry_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String)
    original_filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, server_default=text("'nieuw'"))
    source: Mapped[str] = mapped_column(String, server_default=text("'upload'"))
    source_ref: Mapped[str | None] = mapped_column(String)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("journal_entry.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
