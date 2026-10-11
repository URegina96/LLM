import httpx

from dramas.tmdb import TMDB_API, fetch_korean_dramas, pick_trailer


def fake_tmdb(request: httpx.Request) -> httpx.Response:
    """Подставной TMDB: отвечает заготовками, в интернет не ходим (мок)."""
    path = request.url.path
    if path.endswith("/genre/tv/list"):
        return httpx.Response(200, json={"genres": [{"id": 18, "name": "драма"}]})
    if path.endswith("/discover/tv"):
        return httpx.Response(200, json={"results": [{
            "id": 7, "name": "Тестовая дорама", "original_name": "테스트", "first_air_date": "2016-12-02",
            "vote_average": 8.7, "vote_count": 500, "genre_ids": [18], "overview": "Про любовь",
        }]})
    if path.endswith("/tv/7"):
        return httpx.Response(200, json={
            "poster_path": "/poster.jpg",
            "number_of_episodes": 16,
            "videos": {"results": [{"site": "YouTube", "type": "Trailer", "iso_639_1": "en", "key": "abc"}]},
            "aggregate_credits": {"cast": [
                {"name": "Актриса", "roles": [{"character": "Героиня"}], "profile_path": "/face.jpg"},
                {"name": "Актёр без фото", "roles": [], "profile_path": None},
            ]},
        })
    return httpx.Response(404)


def test_fetch_with_details():
    client = httpx.Client(base_url=TMDB_API, transport=httpx.MockTransport(fake_tmdb))
    [drama] = fetch_korean_dramas(pages=1, client=client)
    assert drama["title"] == "Тестовая дорама"
    assert drama["genres"] == ["драма"]
    assert drama["poster"] == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert drama["trailer"] == "https://www.youtube.com/watch?v=abc"
    assert drama["episodes"] == 16
    assert drama["cast"][0] == {"name": "Актриса", "character": "Героиня",
                                "photo": "https://image.tmdb.org/t/p/w185/face.jpg"}
    assert drama["cast"][1]["photo"] is None


def test_pick_trailer_prefers_russian_trailer():
    videos = [
        {"site": "YouTube", "type": "Teaser", "iso_639_1": "ru", "key": "ru_teaser"},
        {"site": "YouTube", "type": "Trailer", "iso_639_1": "en", "key": "en_trailer"},
        {"site": "YouTube", "type": "Trailer", "iso_639_1": "ru", "key": "ru_trailer"},
        {"site": "Vimeo", "type": "Trailer", "iso_639_1": "ru", "key": "vimeo"},
    ]
    assert pick_trailer(videos).endswith("ru_trailer")


def test_pick_trailer_none():
    assert pick_trailer([{"site": "YouTube", "type": "Behind the Scenes", "iso_639_1": "en", "key": "x"}]) is None
