from guard.output import guard_output


def test_demask_own_data():
    """Метка из вопроса пользователя в ответе заменяется обратно на его данные."""
    safe, leaked = guard_output("Записала ваш номер: [PHONE_1]", {"[PHONE_1]": "+7 999 123-45-67"})
    assert safe == "Записала ваш номер: +7 999 123-45-67"
    assert leaked == []


def test_mask_pii_invented_by_model():
    """Телефон, который модель выдала сама, пользователю не уходит."""
    safe, leaked = guard_output("Позвоните актрисе по номеру 8 912 345 67 89", {})
    assert "912" not in safe
    assert leaked == ["[OUT_PHONE_1]"]


def test_other_users_label_not_demasked():
    """Чужих данных в «шпаргалке» нет — значит, и вернуть их невозможно."""
    safe, _ = guard_output("Номер: [PHONE_1]", {})
    assert safe == "Номер: [PHONE_1]"