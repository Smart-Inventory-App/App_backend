"""Cuánto conviene reponer de un producto para volver a la cobertura configurada."""
import pytest

from app.services.restock import suggested_restock


@pytest.mark.parametrize(
    "daily_rate, coverage_days, stock, expected",
    [
        (2.0, 7, 3, 11),     # 14 unidades para cubrir los días, menos las 3 que quedan
        (0.5, 10, 1, 4),     # se redondea: 5 - 1
        (1.0, 7, 20, 0),     # ya cubre los días: no hace falta reponer
        (1.0, 7, 7, 0),
    ],
)
def test_it_covers_the_configured_days_at_the_current_pace(daily_rate, coverage_days, stock, expected):
    assert suggested_restock(daily_rate, coverage_days, stock) == expected


@pytest.mark.parametrize("daily_rate", [None, 0, 0.0, -1.0])
def test_without_a_consumption_pace_nothing_is_suggested(daily_rate):
    assert suggested_restock(daily_rate, 7, 0) == 0
