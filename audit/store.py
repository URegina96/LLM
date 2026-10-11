import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from audit.models import AuditLog, Base

load_dotenv()
log = logging.getLogger(__name__)

# Подключение к базе: адрес, логин и пароль — из .env
engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
# «Фабрика» сессий: каждая сессия — короткий разговор с базой (одна транзакция)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Создаёт таблицы, которых ещё нет (уже созданные не трогает)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def write_audit(**fields) -> None:
    """Записывает одну строку журнала. База недоступна — пишем ошибку в лог, но чат не роняем."""
    try:
        async with Session() as session:
            session.add(AuditLog(**fields))
            await session.commit()
    except Exception:
        log.exception("Не удалось записать аудит")


def to_dict(row: AuditLog) -> dict:
    """Строка таблицы → словарь для JSON-ответа."""
    return {c.name: getattr(row, c.name) for c in AuditLog.__table__.columns}


async def recent(limit: int = 50) -> list[dict]:
    """Последние записи журнала, новые сверху."""
    async with Session() as session:
        rows = await session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
        return [to_dict(r) for r in rows]


async def stats(days: int = 7) -> list[dict]:
    """Сводка по пользователям за последние N дней: запросы, токены, скорость, ошибки, fallback."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(
            AuditLog.username,
            func.count().label("requests"),
            func.coalesce(func.sum(AuditLog.tokens_in + AuditLog.tokens_out), 0).label("tokens"),
            func.avg(AuditLog.latency_ms).label("avg_latency_ms"),
            func.count().filter(AuditLog.status != 200).label("errors"),
            func.count().filter(AuditLog.answered_model != AuditLog.requested_model).label("fallbacks"),
        )
        .where(AuditLog.created_at >= since)
        .group_by(AuditLog.username)
        .order_by(func.count().desc())
    )
    async with Session() as session:
        result = await session.execute(query)
        return [
            {**row._asdict(), "avg_latency_ms": round(float(row.avg_latency_ms or 0))}
            for row in result
        ]