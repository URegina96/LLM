import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from guard.pii import mask_pii

# Адрес Ollama и модель по умолчанию
OLLAMA_BASE = "http://localhost:11434"
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
    model: str            # какая модель ответила
    masked_question: str  # что на самом деле ушло в нейросеть
    pii_found: list[str]  # какие метки поставили (только метки, без самих данных!)


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


@app.get("/models")
async def list_models() -> list[str]:
    """Список доступных моделей"""
    return await fetch_models()


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Проверяет модель, прячет личные данные, передаёт вопрос в Ollama и возвращает ответ"""
    # Нет такой модели — сразу ошибка 400, в Ollama не ходим
    if req.model not in await fetch_models():
        raise HTTPException(status_code=400, detail=f"Модель '{req.model}' недоступна")

    masked, found = mask_pii(req.message)  # Guard входа: прячем личные данные

    payload = {
        "model": req.model,
        "messages": [
            # system: инструкция для модели, кем ей быть (клиент её не видит)
            {"role": "system", "content": "Ты помощник, который советует дорамы. Отвечай по-русски, коротко."},
            # user: вопрос пользователя, уже БЕЗ личных данных
            {"role": "user", "content": masked},
        ],
        "stream": False,  # получить ответ целиком, а не по кусочкам
    }
    # timeout=120: даём модели до 2 минут (первый запуск бывает медленным)
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
        r.raise_for_status()  # если Ollama ответила ошибкой, сразу сообщить

    return ChatResponse(
        answer=r.json()["message"]["content"],
        model=req.model,
        masked_question=masked,
        pii_found=list(found.keys()),
    )