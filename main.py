import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from guard.pii import mask_pii

# Куда стучаться к нейросети и какую модель просить
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:7b"

# это само наше приложение
app = FastAPI(title="Дорама-GPT")


class ChatRequest(BaseModel):
    """Что присылает пользователь: текст вопроса. Как бланк заказа."""
    message: str


class ChatResponse(BaseModel):
    """Что возвращает сервер: ответ нейросети и что сделал Guard."""
    answer: str
    masked_question: str  # что на самом деле ушло в нейросеть
    pii_found: list[str]  # какие метки поставили (только метки, без самих данных!)


@app.get("/health")
def health():
    """Проверка, жив ли сервер"""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Прячет личные данные, передаёт вопрос в Ollama и возвращает ответ"""
    masked, found = mask_pii(req.message)  # Guard входа: прячем личные данные

    payload = {
        "model": MODEL,
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
        r = await client.post(OLLAMA_URL, json=payload)
        r.raise_for_status()  # если Ollama ответила ошибкой, сразу сообщить

    return ChatResponse(
        answer=r.json()["message"]["content"],
        masked_question=masked,
        pii_found=list(found.keys()),
    )