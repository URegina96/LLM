import asyncio

from audit import store


def run(coro):
    """Запускает async-функцию в обычном тесте."""
    return asyncio.run(coro)


async def fill_and_read():
    # Тесты работают с SQLite в памяти (адрес задан в tests/conftest.py) — Postgres не нужен
    await store.init_db()
    base = {"role": "user", "requested_model": "qwen2.5:7b", "masked_question": "Мой телефон [PHONE_1]",
            "pii_found": ["[PHONE_1]"], "pii_leaked": [], "trace_id": "abc"}
    await store.write_audit(username="user1", status=200, answered_model="qwen2.5:7b",
                            tokens_in=100, tokens_out=20, latency_ms=1000, **base)
    await store.write_audit(username="user1", status=200, answered_model="llama3.2:3b",
                            tokens_in=50, tokens_out=10, latency_ms=3000, **base)
    await store.write_audit(username="user1", status=503, answered_model=None,
                            tokens_in=0, tokens_out=0, latency_ms=200, **base)
    return await store.recent(limit=10), await store.stats(days=7)


def test_write_recent_and_stats():
    rows, stats = run(fill_and_read())
    assert rows[0]["status"] == 503                      # новые сверху
    assert rows[1]["pii_found"] == ["[PHONE_1]"]         # JSON-поле читается обратно списком
    assert "999" not in rows[1]["masked_question"]       # в журнале только замаскированный текст
    [user1] = stats
    assert user1["requests"] == 3
    assert user1["tokens"] == 180
    assert user1["errors"] == 1
    assert user1["fallbacks"] == 1                        # ответила llama вместо qwen
    assert user1["avg_latency_ms"] == 1400


def test_write_audit_does_not_crash_on_bad_data():
    # Нет обязательных полей — запись не получится, но исключение наружу не вылетает
    run(store.write_audit(username="x"))