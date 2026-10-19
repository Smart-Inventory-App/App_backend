from app.utils.sorting import alphabetical_key


def sorted_names(names):
    return sorted(names, key=alphabetical_key)


def test_case_does_not_change_the_order():
    assert sorted_names(["banana", "Cereal", "arroz", "Dulce"]) == ["arroz", "banana", "Cereal", "Dulce"]


def test_accents_do_not_change_the_order():
    assert sorted_names(["Zeta", "Ácido", "ana", "Éxito", "beta"]) == ["Ácido", "ana", "beta", "Éxito", "Zeta"]


def test_enye_comes_after_n_and_before_o():
    assert sorted_names(["oso", "ñandú", "nube", "nz", "Nada"]) == ["Nada", "nube", "nz", "ñandú", "oso"]


def test_an_enye_word_sorts_after_a_plain_n_word_with_the_same_start():
    assert alphabetical_key("na") < alphabetical_key("ña")


def test_an_empty_or_missing_text_sorts_first():
    assert alphabetical_key("") == ""
    assert alphabetical_key(None) == ""
    assert alphabetical_key("") < alphabetical_key("a")
