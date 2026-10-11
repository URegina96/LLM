import json
import re
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path("data/dramas.json")

# Частые слова вопроса, которые ничего не говорят о самой дораме (первые 5 букв)
STOP_STEMS = {"посов", "дорам", "хочу", "какую", "какие", "котор", "рейти", "выше", "больш",
              "чтобы", "можно", "пожал", "подск", "интер", "сериа", "что-т", "лучши", "найди"}


@lru_cache
def load_catalog() -> tuple[dict, ...]:
    """Читает каталог из файла один раз и держит в памяти. Нет файла — пустой каталог."""
    if not DATA_FILE.exists():
        return ()
    return tuple(json.loads(DATA_FILE.read_text(encoding="utf-8"))["items"])


def parse_min_rating(question: str) -> float:
    """«выше 8.5», «от 9», «больше 8,7» → 8.5 / 9.0 / 8.7. Не указано — 0."""
    m = re.search(r"(?:выше|от|больше|>)\s*(\d+(?:[.,]\d+)?)", question.lower())
    return float(m.group(1).replace(",", ".")) if m else 0.0


def search(question: str, catalog: tuple[dict, ...] | None = None, limit: int = 8) -> list[dict]:
    """Простой поиск: фильтр по рейтингу + совпадение слов вопроса с названием, жанрами и описанием."""
    catalog = load_catalog() if catalog is None else catalog
    min_rating = parse_min_rating(question)
    # Слова от 4 букв, обрезанные до 5 букв: «романтическую» и «романтика» → «роман»
    stems = {w[:5] for w in re.findall(r"[а-яёa-z-]{4,}", question.lower())} - STOP_STEMS

    def score(d: dict) -> int:
        text = f"{d['title']} {' '.join(d['genres'])} {d['overview']}".lower()
        return sum(1 for s in stems if s in text)

    candidates = [d for d in catalog if d["rating"] >= min_rating]
    candidates.sort(key=lambda d: (score(d), d["rating"]), reverse=True)
    return candidates[:limit]


def build_system_prompt(dramas: list[dict]) -> str:
    """Инструкция для модели: советовать только из найденных дорам."""
    base = "Ты помощник, который советует корейские дорамы. Отвечай по-русски, коротко."
    if not dramas:
        return base + " Каталог сейчас пуст — честно скажи, что не можешь посоветовать по каталогу."
    lines = [
        f"{i}. {d['title']} ({d['original_title']}), {d['year']}, рейтинг {d['rating']:.1f}, "
        f"жанры: {', '.join(d['genres'])}. {d['overview'][:200]}"
        for i, d in enumerate(dramas, start=1)
    ]
    return (
        base
        + " Советуй ТОЛЬКО дорамы из списка ниже и указывай их рейтинг."
        + " Не придумывай другие названия. Если ничего не подходит — так и скажи.\n\n"
        + "Каталог:\n" + "\n".join(lines)
    )