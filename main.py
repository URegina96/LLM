import httpx
from fastapi import FastAPI
from pydantic import BaseModel

# Куда стучаться к нейросети и какую модель просить
OLLAMA_URL = "http://localhost:11434/api/chat"
# это само наше приложение
app=FastAPI(title = "Дорама-GPT")
MODEL = "qwen2.5:7b"


class ChatRequest(BaseModel):
    """Что присылает пользователь: текст вопроса. Как бланк заказа."""
    message: str


class ChatResponse(BaseModel):
    """Что возвращает сервер: ответ нейросети. Как готовое блюдо на тарелке."""
    answer: str


@app.get("/health")
def health():
    """Проверка, жив ли сервер"""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Передаёт вопрос в Ollama и возвращает ответ"""
    payload = {
        "model": MODEL,
        "messages": [
            # system: инструкция для модели, кем ей быть (клиент её не видит)
            {"role": "system", "content": "Ты помощник, который советует дорамы. Отвечай по-русски, коротко."},
            # user: сам вопрос пользователя
            {"role": "user", "content": req.message},
        ],
        "stream": False,  # получить ответ целиком, а не по кусочкам
    }
    # timeout=120: даём модели до 2 минут (первый запуск бывает медленным)
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(OLLAMA_URL, json=payload)
        r.raise_for_status()  # если Ollama ответила ошибкой, сразу сообщить
    return ChatResponse(answer=r.json()["message"]["content"])

