from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailMessage(Base):
    """A handled mail from the factuurmailbox. Used for dedupe, move-retry and the recent-mails list."""

    __tablename__ = "email_message"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('opgeslagen','alleen_dubbel','geen_bijlage')", name="ck_email_message_outcome"
        ),
        Index("uq_email_message_key", "message_key", unique=True),
        Index("ix_email_message_processed_at", "processed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_key: Mapped[str] = mapped_column(String)
    from_addr: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(String)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    processed_at: Mapped[datetime] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(String)
    documents_new: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    documents_duplicate: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    attachments_skipped: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    moved: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
