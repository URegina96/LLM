import pytest

from guard.pii import mask_pii


@pytest.mark.parametrize(
    "text, expected_label",
    [
        ("звони +7-999-123-45-67", "[PHONE_1]"),
        ("звони 999-123-45-67", "[PHONE_1]"),
        ("почта maria@mail.ru", "[EMAIL_1]"),
        ("карта 4276 1234 5678 9012", "[CARD_1]"),
        ("ip 192.168.1.5", "[IP_1]"),
    ],
)
def test_finds_pii(text, expected_label):
    """Каждый тип ПД находится и заменяется меткой."""
    masked, found = mask_pii(text)
    assert expected_label in masked
    assert expected_label in found


@pytest.mark.parametrize(
    "text",
    [
        "Посоветуй дораму 2016 года с рейтингом 9.1",
        "Версия приложения 1.2.3.4.5",
        "16 серий, 2019-2020",
    ],
)
def test_clean_text_untouched(text):
    """В обычном тексте Guard ничего не трогает (нет ложных срабатываний)."""
    masked, found = mask_pii(text)
    assert masked == text
    assert found == {}


def test_original_value_kept_in_mapping():
    """«Шпаргалка» хранит оригинал — он нужен для демаскировки."""
    _, found = mask_pii("мой номер 8 912 345 67 89")
    assert found == {"[PHONE_1]": "8 912 345 67 89"}


def test_prefix():
    """С приставкой метки другие — не путаются с метками вопроса."""
    masked, _ = mask_pii("ip 10.0.0.1", prefix="OUT_")
    assert masked == "ip [OUT_IP_1]"