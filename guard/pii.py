import re

# Шаблоны (регулярные выражения) для поиска личных данных.
# Порядок важен: карту ищем раньше телефона, чтобы цифры карты не приняли за телефон.
PATTERNS = {
    "EMAIL": re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[a-zA-Z]{2,}"),
    "CARD": re.compile(r"\b(?:\d[ -]?){15}\d\b"),
    "PHONE": re.compile(
        r"(?:\+7|\b[78])[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b"  # с кодом: +7 / 7 / 8
        r"|\b9\d{2}[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b"  # без кода: мобильный с 9
    ),
    "IP": re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"),
}


def mask_pii(text: str) -> tuple[str, dict[str, str]]:
    """Находит личные данные и заменяет их метками вида [PHONE_1].
    Возвращает замаскированный текст и «шпаргалку» метка → оригинал."""
    found: dict[str, str] = {}
    for kind, pattern in PATTERNS.items():
        # findall находит все совпадения; enumerate нумерует их с 1
        for i, value in enumerate(pattern.findall(text), start=1):
            label = f"[{kind}_{i}]"
            found[label] = value
            text = text.replace(value, label, 1)  # заменяем только это одно вхождение
    return text, found


if __name__ == "__main__":
    # Быстрая проверка: запускается, только если запустить этот файл напрямую
    examples = [
        "Я биляш, мой номер +7-999-123-45-67, почта maria.iv@mail.ru",
        "Карта 4276 1234 5678 9012, звони 8 (912) 345-67-89, ip 192.168.1.5",
        "Посоветуй дораму 2016 года с рейтингом 9.1",
        "Звони 999-123-45-67 или 7 912 345 67 89",
        "Слитно: maria.iv@mail.ruЗвони, ip 192.168.1.5Звони",  # edge case
    ]
    for t in examples:
        print(mask_pii(t))