from dramas.catalog import build_system_prompt, parse_min_rating, search

CATALOG = (
    {"title": "Токкэби", "original_title": "도깨비", "year": "2016", "rating": 8.6,
     "genres": ["Драма", "НФ и Фэнтези"], "overview": "Бессмертный гоблин ищет невесту, любовь и смерть.", "url": "u1"},
    {"title": "Внезапно богатые", "original_title": "x", "year": "2020", "rating": 7.9,
     "genres": ["Комедия"], "overview": "Смешная история о деньгах.", "url": "u2"},
    {"title": "Тайный лес", "original_title": "y", "year": "2017", "rating": 8.8,
     "genres": ["Криминал", "Детектив"], "overview": "Прокурор расследует коррупцию.", "url": "u3"},
)


def test_parse_min_rating():
    assert parse_min_rating("посоветуй с рейтингом выше 8.5") == 8.5
    assert parse_min_rating("от 9") == 9.0
    assert parse_min_rating("больше 8,7") == 8.7
    assert parse_min_rating("просто дораму") == 0.0


def test_search_by_words():
    """«про любовь» поднимает наверх дораму, где в описании есть «любовь»."""
    assert search("посоветуй дораму про любовь", CATALOG)[0]["title"] == "Токкэби"


def test_search_by_genre():
    assert search("хочу детектив", CATALOG)[0]["title"] == "Тайный лес"


def test_search_min_rating_filter():
    titles = [d["title"] for d in search("комедию выше 8", CATALOG)]
    assert "Внезапно богатые" not in titles  # рейтинг 7.9 — отсечён


def test_prompt_lists_only_catalog():
    prompt = build_system_prompt(list(CATALOG[:1]))
    assert "Токкэби" in prompt and "ТОЛЬКО" in prompt


def test_prompt_empty_catalog():
    assert "пуст" in build_system_prompt([])