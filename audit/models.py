from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Общий предок всех таблиц: SQLAlchemy по нему находит, какие таблицы создавать."""


class AuditLog(Base):
    """Журнал аудита: одна строка = один запрос к /chat. Только замаскированные данные!"""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    username: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[int]                                             # HTTP-код ответа: 200, 503…
    requested_model: Mapped[str] = mapped_column(String(64))
    answered_model: Mapped[str | None] = mapped_column(String(64))  # None — никто не ответил
    masked_question: Mapped[str] = mapped_column(Text)              # вопрос ПОСЛЕ Guard входа
    pii_found: Mapped[list[str]] = mapped_column(JSON, default=list)   # метки, без самих данных
    pii_leaked: Mapped[list[str]] = mapped_column(JSON, default=list)
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int]
    trace_id: Mapped[str | None] = mapped_column(String(64))        # id трейса в Langfuse