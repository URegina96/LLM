from guard.pii import mask_pii


def guard_output(answer: str, found: dict[str, str]) -> tuple[str, list[str]]:
    """Guard выхода: проверяет ответ модели перед отправкой пользователю.
    1) Прячет ПД, которые модель выдала сама (их не было в вопросе) — метки [OUT_PHONE_1] и т.п.
    2) Демаскировка: возвращает пользователю ЕГО данные вместо меток [PHONE_1] из вопроса.
    Возвращает безопасный ответ и список меток ПД, найденных в ответе модели."""
    safe, leaked = mask_pii(answer, prefix="OUT_")
    # found — «шпаргалка» из Guard входа этого же запроса, то есть только данные самого пользователя
    for label, value in found.items():
        safe = safe.replace(label, value)
    return safe, list(leaked.keys())