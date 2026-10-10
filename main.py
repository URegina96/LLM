from fastapi import FastAPI

# это само наше приложение
app=FastAPI(title = "Дорама-GPT")

@app.get("/health")
def health():
    """Проверка, жив ли сервер"""
    return {"status": "ok"}


@app.get("/hello/{name}")
def hello(name: str):
    """Приветствие по имени. Пример, как сервер получает данные прямо из адреса."""
    return {"message": f"Привет, {name}! Скоро я буду советовать дорамы, которые тебе понравятся"}