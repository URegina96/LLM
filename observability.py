import os

from dotenv import load_dotenv
from langfuse import Langfuse

from guard.pii import mask_pii

load_dotenv()


def mask_for_langfuse(*, data, **kwargs):
    """Второй рубеж защиты: перед отправкой в Langfuse прячем PII во ВСЕХ строках трейса.
    Обходит вложенные dict и list и маскирует каждую строку внутри."""
    if isinstance(data, str):
        return mask_pii(data)[0]
    if isinstance(data, dict):
        return {k: mask_for_langfuse(data=v) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_for_langfuse(data=v) for v in data]
    return data  # числа, None и прочее — как есть


# Клиент Langfuse: ключи и адрес берём из .env, маскировку подключаем через mask=
langfuse = Langfuse(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
    base_url=os.environ["LANGFUSE_BASE_URL"],
    mask=mask_for_langfuse,
)