import os
from datetime import date

import redis.asyncio as redis
from fastapi import HTTPException

# Адрес Redis: из переменной окружения (в Docker — другой), по умолчанию — этот компьютер.
# 127.0.0.1, а не localhost: на Windows localhost сначала идёт через IPv6 и зависает
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"), decode_responses=True)

# Сколько запросов в день можно каждой роли (None — без лимита)
ROLE_DAILY_LIMIT = {"admin": None, "user": 100, "guest": 5}

DAY_SECONDS = 24 * 60 * 60


def _keys(username: str) -> tuple[str, str]:
    """Ключи в Redis на сегодня: счётчик запросов и счётчик LLM-токенов пользователя."""
    today = date.today().isoformat()  # например 2026-10-11
    return f"usage:{username}:{today}:requests", f"usage:{username}:{today}:tokens"


async def check_and_count_request(username: str, role: str) -> None:
    """+1 запрос пользователю. Если лимит превышен — ошибка 429."""
    req_key, _ = _keys(username)
    count = await redis_client.incr(req_key)  # атомарно +1 (нет ключа — создаст со значением 1)
    if count == 1:
        await redis_client.expire(req_key, DAY_SECONDS)  # через сутки Redis сам удалит ключ
    limit = ROLE_DAILY_LIMIT[role]
    if limit is not None and count > limit:
        await redis_client.decr(req_key)  # отказанный запрос не считаем
        raise HTTPException(status_code=429, detail=f"Лимит {limit} запросов в день исчерпан")


async def refund_request(username: str) -> None:
    """Возвращает запрос в квоту: модель не ответила, значит, пользователь ничего не получил."""
    req_key, _ = _keys(username)
    await redis_client.decr(req_key)


# Защита входа от перебора паролей: не больше 5 неудачных попыток на логин за 15 минут
LOGIN_MAX_FAILURES = 5
LOGIN_BLOCK_SECONDS = 15 * 60


async def check_login_allowed(username: str) -> None:
    """Слишком много неудачных попыток входа — 429, пароль даже не проверяем."""
    failures = int(await redis_client.get(f"login_fail:{username}") or 0)
    if failures >= LOGIN_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Слишком много попыток входа. Попробуйте через 15 минут")


async def register_login_failure(username: str) -> None:
    """+1 неудачная попытка; счётчик сам исчезнет через 15 минут после последней ошибки."""
    key = f"login_fail:{username}"
    await redis_client.incr(key)
    await redis_client.expire(key, LOGIN_BLOCK_SECONDS)


async def reset_login_failures(username: str) -> None:
    """Успешный вход обнуляет счётчик неудачных попыток."""
    await redis_client.delete(f"login_fail:{username}")


async def add_tokens(username: str, tokens: int) -> None:
    """Добавляет потраченные LLM-токены в счётчик пользователя за сегодня."""
    _, tok_key = _keys(username)
    await redis_client.incrby(tok_key, tokens)
    await redis_client.expire(tok_key, DAY_SECONDS)


async def get_usage(username: str, role: str) -> dict:
    """Сколько запросов и LLM-токенов пользователь потратил сегодня."""
    req_key, tok_key = _keys(username)
    requests_used, tokens_used = await redis_client.mget(req_key, tok_key)  # два ключа за один запрос
    return {
        "requests_used": int(requests_used or 0),
        "requests_limit": ROLE_DAILY_LIMIT[role],
        "tokens_used": int(tokens_used or 0),
    }