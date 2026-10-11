import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

load_dotenv()  # читает файл .env и кладёт значения в переменные окружения

SECRET_KEY = os.environ["SECRET_KEY"]  # ключ подписи токенов (из .env, не из кода!)
ALGORITHM = "HS256"                    # алгоритм подписи
TOKEN_TTL_MINUTES = 60                 # сколько живёт токен

# Пользователи. Пароли храним ТОЛЬКО в виде хешей bcrypt.
USERS = {
    # пользователи и хеши паролей хранятся вне репозитория (users.json)
}

# RBAC: какие модели разрешены каждой роли
ROLE_MODELS = {
    "admin": {"qwen2.5:7b", "llama3.2:3b"},
    "user": {"qwen2.5:7b", "llama3.2:3b"},
    "guest": {"llama3.2:3b"},
}

# Токен приходит в заголовке "Authorization: Bearer <токен>", выдаётся на /token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def hash_password(password: str) -> str:
    """Превращает пароль в хеш bcrypt. Обратно пароль из хеша не получить."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def authenticate(username: str, password: str) -> dict | None:
    """Проверяет логин и пароль. Возвращает пользователя или None."""
    user = USERS.get(username)
    if user and bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return {"username": username, "role": user["role"]}
    return None


def create_token(username: str, role: str) -> str:
    """Выпускает JWT: внутри логин, роль и срок жизни, всё подписано SECRET_KEY."""
    payload = {
        "sub": username,  # sub (subject) — стандартное поле «кому выдан токен»
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Достаёт токен из запроса, проверяет подпись и срок. Нет или плохой токен → 401."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или просроченный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"username": payload["sub"], "role": payload["role"]}


if __name__ == "__main__":
    # Генератор хешей: python guard/auth.py → ввести пароль → скопировать хеш в USERS
    print(hash_password(input("Пароль: ")))