import json
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

from dramas.catalog import DATA_FILE

load_dotenv()

TMDB_API = "https://api.themoviedb.org/3"

# Не дорамы: мультфильмы, документальные, новости, реалити, ток-шоу
EXCLUDED_GENRES = "16,99,10763,10764,10767"


def fetch_korean_dramas(pages: int = 5, client: httpx.Client | None = None) -> list[dict]:
    """Скачивает из TMDB корейские сериалы с лучшим рейтингом (20 штук на страницу)."""
    client = client or httpx.Client(
        base_url=TMDB_API,
        headers={"Authorization": f"Bearer {os.environ['TMDB_TOKEN']}"},
        timeout=30,
    )
    with client:
        # Справочник жанров: id → название на русском
        r = client.get("/genre/tv/list", params={"language": "ru-RU"})
        r.raise_for_status()
        genres = {g["id"]: g["name"] for g in r.json()["genres"]}

        dramas = []
        for page in range(1, pages + 1):
            r = client.get("/discover/tv", params={
                "with_origin_country": "KR",      # только Корея
                "without_genres": EXCLUDED_GENRES,
                "sort_by": "vote_average.desc",   # сначала с лучшим рейтингом
                "vote_count.gte": 100,            # отсекаем сериалы с парой случайных оценок
                "language": "ru-RU",              # названия и описания на русском
                "page": page,
            })
            r.raise_for_status()
            for show in r.json()["results"]:
                dramas.append({
                    "id": show["id"],
                    "title": show["name"],
                    "original_title": show["original_name"],
                    "year": (show.get("first_air_date") or "")[:4],
                    "rating": show["vote_average"],
                    "votes": show["vote_count"],
                    "genres": [genres.get(g, "") for g in show["genre_ids"]],
                    "overview": show.get("overview", ""),
                    "url": f"https://www.themoviedb.org/tv/{show['id']}",
                })
    return dramas


def save_catalog(dramas: list[dict]) -> None:
    """Сохраняет каталог в data/dramas.json вместе с паспортом источника."""
    DATA_FILE.parent.mkdir(exist_ok=True)
    catalog = {
        "source": "tmdb",
        "classification": "PUBLIC",  # открытые данные: ПД нет, можно отдавать любой роли
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "items": dramas,
    }
    DATA_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    # Загрузка каталога: python -m dramas.tmdb
    items = fetch_korean_dramas()
    save_catalog(items)
    print(f"Сохранено дорам: {len(items)} → {DATA_FILE}")
    for d in items[:5]:
        print(f"  {d['rating']:.1f}  {d['title']} ({d['year']})")