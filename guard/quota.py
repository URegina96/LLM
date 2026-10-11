from datetime import date

import redis.asyncio as redis
from fastapi import HTTPException

# Подключение к Redis (запущен в Docker на порту 6379).
# 127.0.0.1, а не localhost: на Windows localhost сначала идёт через IPv6 и зависает
redis_client = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)

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