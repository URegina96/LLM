import httpx

from guard.quota import redis_client
from observability import langfuse

OLLAMA_BASE = "http://localhost:11434"

# Маршруты: какую модель пробовать следующей, если эта не ответила
FALLBACKS = {
    "qwen2.5:7b": ["llama3.2:3b"],
    "llama3.2:3b": [],
}

# Feature flag в Redis: множество моделей, которые админ пометил «упавшими»
DOWN_KEY = "flags:models_down"


class AllModelsFailed(Exception):
    """Ни одна модель из цепочки не ответила."""


async def call_ollama(model: str, messages: list[dict]) -> dict:
    """Один вызов модели. Сбой сети, таймаут или ошибка Ollama — исключение."""
    if await redis_client.sismember(DOWN_KEY, model):
        raise httpx.ConnectError(f"Модель {model} отключена флагом (имитация сбоя)")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
        )
        r.raise_for_status()
    return r.json()


async def chat_with_fallback(model: str, allowed: set[str], messages: list[dict]) -> tuple[str, dict]:
    """Пробует модель, при сбое — запасные из FALLBACKS (только разрешённые роли).
    Возвращает: какая модель ответила, и ответ Ollama."""
    chain = [model] + [m for m in FALLBACKS.get(model, []) if m in allowed]
    errors = []
    for candidate in chain:
        # Каждая попытка — отдельный шаг в трейсе Langfuse
        with langfuse.start_as_current_observation(
            name=f"ollama:{candidate}", as_type="generation", model=candidate, input=messages
        ) as gen:
            try:
                data = await call_ollama(candidate, messages)
            except httpx.HTTPError as e:
                gen.update(level="ERROR", status_message=str(e))  # в Langfuse шаг станет красным
                errors.append(f"{candidate}: {e}")
                continue  # пробуем следующую модель
            usage = {"input": data.get("prompt_eval_count", 0), "output": data.get("eval_count", 0)}
            gen.update(output=data["message"]["content"], usage_details=usage)
            return candidate, data
    raise AllModelsFailed("; ".join(errors))