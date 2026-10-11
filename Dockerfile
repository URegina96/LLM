# Образ гейтвея: Python + наш код. Собирается командой docker compose build
FROM python:3.13-slim

# Не создавать .pyc и сразу печатать логи (без буфера) — удобно в контейнере
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала только зависимости: этот слой кешируется и не пересобирается, пока requirements.txt не изменился
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Потом код (меняется часто — пересобирается только этот слой)
COPY . .

# Запускаем не от root: если в приложении найдут дыру, у взломщика будет меньше прав
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]