import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from langfuse import propagate_attributes
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from audit.store import init_db, recent, stats, write_audit
from dramas.catalog import build_system_prompt, search
from guard.auth import ROLE_MODELS, authenticate, create_token, get_current_user, require_admin
from guard.output import guard_output
from guard.pii import mask_pii
from guard.quota import (
    add_tokens,
    check_and_count_request,
    check_login_allowed,
    get_usage,
    redis_client,
    refund_request,
    register_login_failure,
    reset_login_failures,
)
from monitoring import FALLBACKS, LLM_TOKENS, metrics_endpoint, metrics_middleware, record_pii
from observability import langfuse
from router import DOWN_KEY, OLLAMA_BASE, AllModelsFailed, chat_with_fallback

# Модель по умолчанию, если клиент не указал свою
DEFAULT_MODEL = "qwen2.5:7b"

# Папка со страницей чата
WEB_DIR = Path(__file__).parent / "web"

# Список моделей Ollama кешируем: он меняется редко, а спрашивать его на каждый вопрос — лишний запрос
MODELS_CACHE_SECONDS = 30
_models_cache: tuple[float, list[str]] = (0.0, [])

# Какие поля дорамы отдаём странице для карточек (d.get: в старом каталоге постеров может не быть)
SOURCE_FIELDS = ("title", "original_title", "year", "rating", "genres", "overview", "url",
                 "poster", "trailer", "episodes", "cast")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Что сделать при старте сервера (до первого запроса) и при остановке."""
    await init_db()  # создать таблицы в PostgreSQL, если их ещё нет
    yield            # здесь сервер работает


# это само наше приложение
app = FastAPI(title="Дорама-GPT", lifespan=lifespan)
# Замер каждого запроса (время, код ответа) для Prometheus
app.middleware("http")(metrics_middleware)


@app.get("/", include_in_schema=False)
def index():
    """Страница чата. В Swagger её не показываем."""
    return FileResponse(WEB_DIR / "index.html")


class ChatRequest(BaseModel):
    """Что присылает пользователь: текст вопроса и (необязательно) модель."""
    message: str
    model: str = DEFAULT_MODEL  # не указали модель — берём модель по умолчанию


class ChatResponse(BaseModel):
    """Что возвращает сервер: ответ нейросети и что сделал Guard."""
    answer: str
    model: str             # какая модель ответила
    fallback_used: bool    # ответила не та модель, которую просили
    masked_question: str   # что на самом деле ушло в нейросеть
    pii_found: list[str]   # какие метки поставили (только метки, без самих данных!)
    pii_leaked: list[str]  # какие ПД Guard выхода нашёл и спрятал в ответе модели
    sources: list[dict]    # дорамы из каталога, которые получила модель (для карточек на странице)
    tokens_used: int       # сколько LLM-токенов ушло на этот запрос


async def fetch_models() -> list[str]:
    """Имена моделей, скачанных в Ollama (кеш на 30 секунд). Ollama недоступна — 503."""
    global _models_cache
    fetched_at, models = _models_cache
    if time.monotonic() - fetched_at < MODELS_CACHE_SECONDS:
        return models
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Модели сейчас недоступны, попробуйте позже")
    models = [m["name"] for m in r.json()["models"]]
    _models_cache = (time.monotonic(), models)
    return models


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Метрики для Prometheus (запросы, задержка, токены, ПД, GPU)."""
    return metrics_endpoint()


@app.get("/health")
def health():
    """Проверка, жив ли сервер"""
    return {"status": "ok"}


@app.post("/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    """Логин: проверяет логин и пароль и выдаёт JWT-токен. 5 ошибок подряд — блок на 15 минут."""
    await check_login_allowed(form.username)
    # bcrypt специально медленный — считаем его в отдельном потоке, чтобы не тормозить остальные запросы
    user = await run_in_threadpool(authenticate, form.username, form.password)
    if not user:
        await register_login_failure(form.username)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    await reset_login_failures(form.username)
    return {"access_token": create_token(user["username"], user["role"]), "token_type": "bearer"}


@app.get("/me")
def me(user: dict = Depends(get_current_user)):
    """Кто я: данные из токена"""
    return user


@app.get("/usage")
async def usage(user: dict = Depends(get_current_user)):
    """Сколько запросов и LLM-токенов я потратила сегодня"""
    return await get_usage(user["username"], user["role"])


@app.get("/models")
async def list_models(user: dict = Depends(get_current_user)) -> list[str]:
    """Список моделей, доступных роли пользователя"""
    allowed = ROLE_MODELS[user["role"]]
    return [m for m in await fetch_models() if m in allowed]


@app.post("/admin/models/{model}/down")
async def mark_model_down(model: str, admin: dict = Depends(require_admin)):
    """Админ: пометить модель «упавшей» (имитация сбоя для проверки fallback)"""
    await redis_client.sadd(DOWN_KEY, model)
    return {"down": sorted(await redis_client.smembers(DOWN_KEY))}


@app.delete("/admin/models/{model}/down")
async def mark_model_up(model: str, admin: dict = Depends(require_admin)):
    """Админ: вернуть модель в строй"""
    await redis_client.srem(DOWN_KEY, model)
    return {"down": sorted(await redis_client.smembers(DOWN_KEY))}


@app.get("/admin/audit")
async def audit_log(limit: int = 50, admin: dict = Depends(require_admin)):
    """Админ: последние записи журнала аудита"""
    return await recent(limit)


@app.get("/admin/audit/stats")
async def audit_stats(days: int = 7, admin: dict = Depends(require_admin)):
    """Админ: сводка по пользователям за N дней (SQL GROUP BY)"""
    return await stats(days)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    """Проверяет модель, права и квоту, прячет PII на входе и выходе, ищет в каталоге, спрашивает модель, пишет трейс"""
    start = time.perf_counter()  # для журнала: сколько занял запрос
    # Нет такой модели — 400
    if req.model not in await fetch_models():
        raise HTTPException(status_code=400, detail=f"Модель '{req.model}' недоступна")
    # Модель есть, но роли она не разрешена — 403
    if req.model not in ROLE_MODELS[user["role"]]:
        raise HTTPException(status_code=403, detail=f"Роли '{user['role']}' модель '{req.model}' запрещена")
    # Квота: +1 запрос; если лимит исчерпан — 429
    await check_and_count_request(user["username"], user["role"])

    # Всё внутри — один трейс, привязанный к пользователю и его роли
    with propagate_attributes(user_id=user["username"], tags=[f"role:{user['role']}"]):
        with langfuse.start_as_current_observation(name="chat", input=req.message) as root:
            trace_id = langfuse.get_current_trace_id()  # чтобы из журнала найти трейс в Langfuse

            # Шаг трейса 1: Guard входа
            with langfuse.start_as_current_observation(name="pii-guard", as_type="guardrail") as guard_span:
                masked, found = mask_pii(req.message)
                guard_span.update(input=req.message, output={"masked": masked, "pii_found": list(found.keys())})

            # Шаг трейса 2: поиск в каталоге дорам (RAG: даём модели настоящие данные)
            with langfuse.start_as_current_observation(name="catalog-search", as_type="retriever", input=masked) as ret:
                dramas = search(masked)
                ret.update(output=[f"{d['title']} ({d['rating']:.1f})" for d in dramas])

            messages = [
                # system: инструкция + найденные дорамы (клиент её не видит)
                {"role": "system", "content": build_system_prompt(dramas)},
                # user: вопрос пользователя, уже БЕЗ личных данных
                {"role": "user", "content": masked},
            ]

            # Шаг трейса 3: модель с запасными (каждая попытка — отдельный шаг в Langfuse)
            try:
                answered_by, data = await chat_with_fallback(req.model, ROLE_MODELS[user["role"]], messages)
            except AllModelsFailed as e:
                root.update(level="ERROR", status_message=str(e))
                await write_audit(
                    username=user["username"], role=user["role"], status=503,
                    requested_model=req.model, answered_model=None,
                    masked_question=masked, pii_found=list(found.keys()), pii_leaked=[],
                    latency_ms=round((time.perf_counter() - start) * 1000), trace_id=trace_id,
                )
                await refund_request(user["username"])  # ответа не было — запрос в квоту не засчитываем
                raise HTTPException(status_code=503, detail="Все модели сейчас недоступны, попробуйте позже")

            answer = data["message"]["content"]
            # Ollama сообщает, сколько токенов ушло на вопрос и на ответ
            usage = {"input": data.get("prompt_eval_count", 0), "output": data.get("eval_count", 0)}

            # Шаг трейса 4: Guard выхода — прячем ПД, которые выдала модель, и возвращаем пользователю его данные
            with langfuse.start_as_current_observation(name="output-guard", as_type="guardrail") as out_span:
                safe_answer, leaked = guard_output(answer, found)
                out_span.update(input=answer, output={"pii_leaked": leaked})

            root.update(
                output=answer,
                metadata={"requested_model": req.model, "answered_by": answered_by, "pii_leaked": leaked},
            )

    tokens = usage["input"] + usage["output"]
    await add_tokens(user["username"], tokens)

    # Метрики для Prometheus
    LLM_TOKENS.labels(model=answered_by, direction="input").inc(usage["input"])
    LLM_TOKENS.labels(model=answered_by, direction="output").inc(usage["output"])
    record_pii("input", list(found.keys()))
    record_pii("output", leaked)
    if answered_by != req.model:
        FALLBACKS.labels(requested=req.model, answered=answered_by).inc()

    # Журнал аудита в PostgreSQL: кто, когда, какая модель, что нашёл Guard (без самих ПД)
    await write_audit(
        username=user["username"], role=user["role"], status=200,
        requested_model=req.model, answered_model=answered_by,
        masked_question=masked, pii_found=list(found.keys()), pii_leaked=leaked,
        tokens_in=usage["input"], tokens_out=usage["output"],
        latency_ms=round((time.perf_counter() - start) * 1000), trace_id=trace_id,
    )

    return ChatResponse(
        answer=safe_answer,
        model=answered_by,
        fallback_used=answered_by != req.model,
        masked_question=masked,
        pii_found=list(found.keys()),
        pii_leaked=leaked,
        sources=[{k: d.get(k) for k in SOURCE_FIELDS} for d in dramas],
        tokens_used=tokens,
    )