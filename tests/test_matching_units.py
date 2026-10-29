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


# ── búsqueda por texto: nombre, marca y descripción ───────────────────────────

class _Item:
    def __init__(self, nombre, marca=None, descripcion=None):
        self.nombre, self.marca, self.descripcion = nombre, marca, descripcion


def test_puntuar_texto_finds_a_product_when_all_its_name_words_are_in_the_text():
    item = _Item("Yogur Ser")
    assert matching.puntuar_texto("SER Yogur entero frutilla 1L", item) >= matching.UMBRAL_CONFIABLE


def test_puntuar_texto_uses_the_brand():
    item = _Item("Cremoso", marca="La Serenisima")
    assert matching.puntuar_texto("la serenisima queso untable", item) >= matching.UMBRAL_CANDIDATO
    assert matching.puntuar_texto("otra marca distinta", item) < matching.UMBRAL_CANDIDATO


def test_puntuar_texto_uses_the_description():
    item = _Item("Producto 7", descripcion="Aceite de girasol alto oleico")
    assert matching.puntuar_texto("aceite girasol alto oleico", item) >= matching.UMBRAL_CANDIDATO
    assert matching.puntuar_texto("galletitas dulces", item) < matching.UMBRAL_CANDIDATO


def test_puntuar_texto_finds_a_short_text_inside_name_brand_or_description():
    assert matching.puntuar_texto("yog", _Item("Yogur Ser")) >= 0.9
    assert matching.puntuar_texto("sere", _Item("Cremoso", marca="La Serenisima")) >= 0.75
    assert matching.puntuar_texto("girasol", _Item("Aceite", descripcion="De girasol")) >= 0.7


def test_puntuar_texto_without_words_falls_back_to_the_name_score():
    assert matching.puntuar_texto("1l", _Item("Leche")) < matching.UMBRAL_CANDIDATO


def test_buscar_texto_returns_the_best_first_and_nothing_for_an_empty_text():
    items = [_Item("Detergente"), _Item("Yogur Ser"), _Item("Yogur Ser Light")]
    found = matching.buscar_texto("yogur ser", items)
    assert [p.nombre for p, _ in found] == ["Yogur Ser", "Yogur Ser Light"]
    assert matching.buscar_texto("   ", items) == []
    assert matching.buscar_texto(None, items) == []
