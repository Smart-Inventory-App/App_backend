"""Casos borde de `app.core.matching` que `test_scan_matching.py` no llega a
tocar porque siempre pasa por `buscar()`, que ya filtra las lecturas vacías
antes de emparejar."""
from app.core import matching

def test_normalizar_of_nothing_is_an_empty_string():
    assert matching.normalizar(None) == ""
    assert matching.normalizar("") == ""

def test_es_abreviatura_is_false_when_either_side_has_no_words():
    assert matching._es_abreviatura("", "yogur ser") is False
    assert matching._es_abreviatura("yog", "") is False

def test_parecido_is_zero_when_either_side_is_empty():
    assert matching.parecido("", "Yogur") == 0.0
    assert matching.parecido("Yogur", "") == 0.0
