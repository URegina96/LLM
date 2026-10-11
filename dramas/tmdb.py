import json
import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

from dramas.catalog import DATA_FILE

load_dotenv()

TMDB_API = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"  # картинки TMDB: {IMAGE_BASE}/{размер}{путь}

# Не дорамы: мультфильмы, документальные, новости, реалити, ток-шоу
EXCLUDED_GENRES = "16,99,10763,10764,10767"


def image_url(path: str | None, size: str) -> str | None:
    """Путь картинки из TMDB → полная ссылка. Нет картинки — None."""
    return f"{IMAGE_BASE}/{size}{path}" if path else None


def pick_trailer(videos: list[dict]) -> str | None:
    """Трейлер на YouTube: сначала на русском, потом любой; тизер — если трейлера нет."""
    youtube = [v for v in videos if v["site"] == "YouTube" and v["type"] in ("Trailer", "Teaser")]
    youtube.sort(key=lambda v: (v.get("iso_639_1") != "ru", v["type"] != "Trailer"))
    return f"https://www.youtube.com/watch?v={youtube[0]['key']}" if youtube else None


def fetch_details(client: httpx.Client, show_id: int) -> dict:
    """Подробности одной дорамы: постер, трейлер, число серий и актёры (одним запросом)."""
    r = client.get(f"/tv/{show_id}", params={
        "language": "ru-RU",
        "append_to_response": "videos,aggregate_credits",  # видео и актёры в том же ответе
        "include_video_language": "ru,en,ko,null",          # трейлеры на русском часто нет — берём и другие
    })
    r.raise_for_status()
    d = r.json()
    cast = [
        {
            "name": c["name"],
            "character": c["roles"][0]["character"] if c.get("roles") else "",
            "photo": image_url(c.get("profile_path"), "w185"),
        }
        for c in d.get("aggregate_credits", {}).get("cast", [])[:8]  # 8 главных актёров
    ]
    return {
        "poster": image_url(d.get("poster_path"), "w342"),
        "trailer": pick_trailer(d.get("videos", {}).get("results", [])),
        "episodes": d.get("number_of_episodes"),
        "cast": cast,
    }


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
                    **fetch_details(client, show["id"]),  # постер, трейлер, серии, актёры
                })
            print(f"  страница {page}/{pages}: всего {len(dramas)} дорам")
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