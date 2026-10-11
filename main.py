import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from langfuse import propagate_attributes
from pydantic import BaseModel

from guard.auth import ROLE_MODELS, authenticate, create_token, get_current_user, require_admin
from guard.output import guard_output
from guard.pii import mask_pii
from guard.quota import add_tokens, check_and_count_request, get_usage, redis_client
from observability import langfuse
from router import DOWN_KEY, OLLAMA_BASE, AllModelsFailed, chat_with_fallback

# Модель по умолчанию, если клиент не указал свою
DEFAULT_MODEL = "qwen2.5:7b"

# это само наше приложение
app = FastAPI(title="Дорама-GPT")


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
    tokens_used: int       # сколько LLM-токенов ушло на этот запрос


async def fetch_models() -> list[str]:
    """Спрашивает у Ollama, какие модели скачаны, и возвращает их имена."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{OLLAMA_BASE}/api/tags")
        r.raise_for_status()
    return [m["name"] for m in r.json()["models"]]


@app.get("/health")
def health():
    """Проверка, жив ли сервер"""
    return {"status": "ok"}


@app.post("/token")
def login(form: OAuth2PasswordRequestForm = Depends()):
    """Логин: проверяет логин и пароль и выдаёт JWT-токен."""
    user = authenticate(form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
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


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    """Проверяет модель, права и квоту, прячет PII на входе и выходе, спрашивает модель (с fallback), пишет трейс"""
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

            # Шаг трейса 1: Guard входа
            with langfuse.start_as_current_observation(name="pii-guard", as_type="guardrail") as guard_span:
                masked, found = mask_pii(req.message)
                guard_span.update(input=req.message, output={"masked": masked, "pii_found": list(found.keys())})

            messages = [
                # system: инструкция для модели, кем ей быть (клиент её не видит)
                {"role": "system", "content": "Ты помощник, который советует дорамы. Отвечай по-русски, коротко."},
                # user: вопрос пользователя, уже БЕЗ личных данных
                {"role": "user", "content": masked},
            ]

            # Шаг трейса 2: модель с запасными (каждая попытка — отдельный шаг в Langfuse)
            try:
                answered_by, data = await chat_with_fallback(req.model, ROLE_MODELS[user["role"]], messages)
            except AllModelsFailed as e:
                root.update(level="ERROR", status_message=str(e))
                raise HTTPException(status_code=503, detail="Все модели сейчас недоступны, попробуйте позже")

            answer = data["message"]["content"]
            # Ollama сообщает, сколько токенов ушло на вопрос и на ответ
            usage = {"input": data.get("prompt_eval_count", 0), "output": data.get("eval_count", 0)}

            # Шаг трейса 3: Guard выхода — прячем ПД, которые выдала модель, и возвращаем пользователю его данные
            with langfuse.start_as_current_observation(name="output-guard", as_type="guardrail") as out_span:
                safe_answer, leaked = guard_output(answer, found)
                out_span.update(input=answer, output={"pii_leaked": leaked})

            root.update(
                output=answer,
                metadata={"requested_model": req.model, "answered_by": answered_by, "pii_leaked": leaked},
            )

    tokens = usage["input"] + usage["output"]
    await add_tokens(user["username"], tokens)

    return ChatResponse(
        answer=safe_answer,
        model=answered_by,
        fallback_used=answered_by != req.model,
        masked_question=masked,
        pii_found=list(found.keys()),
        pii_leaked=leaked,
        tokens_used=tokens,
    )