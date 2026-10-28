"""Las reglas de las alertas: de dónde sale cada límite y cuándo una alerta es crítica o una advertencia."""
from datetime import date

import pytest

from app.models.profile import UserProfile
from app.services import alert_rules, alert_texts


@pytest.mark.parametrize("limit, margin", [(1, 2), (2, 2), (4, 2), (7, 4), (10, 5), (30, 15)])
def test_near_the_limit_is_half_of_it_with_a_minimum_of_two_days(limit, margin):
    assert alert_rules.near_margin(limit) == margin


def test_the_rule_of_the_product_beats_the_general_one_which_beats_the_default():
    assert alert_rules.resolve_limit(14, 3, 7) == (14, "product")
    assert alert_rules.resolve_limit(None, 3, 7) == (3, "general")
    assert alert_rules.resolve_limit(None, None, 7) == (7, "general")
    assert alert_rules.resolve_limit(0, None, 7) == (7, "general")


def test_the_limits_come_from_the_profile_when_the_product_has_no_rule():
    profile = UserProfile(user_id="u", dias_alerta_vencimiento=5, stock_minimo=9)
    assert alert_rules.expiry_limit(None, profile) == (5, "general")
    assert alert_rules.expiry_limit(2, profile) == (2, "product")
    assert alert_rules.coverage_limit(None, profile) == (9, "general")
    assert alert_rules.coverage_limit(20, profile) == (20, "product")


def test_without_a_profile_the_factory_limits_apply():
    assert alert_rules.expiry_limit(None, None) == (7, "general")
    assert alert_rules.coverage_limit(None, None) == (7, "general")


@pytest.mark.parametrize("days, expected", [(-5, "critical"), (0, "critical"), (6, "critical"), (7, "warning"), (10, "warning"), (11, None)])
def test_expiry_levels_with_a_limit_of_seven_days(days, expected):
    assert alert_rules.expiry_level(days, 7) == expected


@pytest.mark.parametrize("days, expected", [(0, "critical"), (6, "critical"), (7, "warning"), (10, "warning"), (11, None), (None, None)])
def test_stock_levels_with_a_minimum_of_seven_days(days, expected):
    assert alert_rules.coverage_level(days, 7) == expected


def test_days_until_counts_from_today():
    assert alert_rules.days_until(date(2026, 1, 11), today=date(2026, 1, 1)) == 10
    assert alert_rules.days_until(date(2025, 12, 30), today=date(2026, 1, 1)) == -2
    assert alert_rules.days_until(date.today()) == 0


@pytest.mark.parametrize("value, expected", [(None, None), (0, 0), (0.4, 0), (2.6, 3), (-3, 0), (12, 12)])
def test_the_days_of_the_model_are_rounded_and_never_negative(value, expected):
    assert alert_rules.whole_days(value) == expected


def test_a_time_is_never_said_as_zero_days():
    assert alert_texts.when(0) == "hoy"
    assert alert_texts.when(-1) == "hoy"
    assert alert_texts.when(1) == "mañana"
    assert alert_texts.when(5) == "en 5 días"


def test_the_messages_of_the_notifications():
    assert alert_texts.low_coverage_body("Leche", 0) == "Según tu consumo, Leche se agotará hoy."
    assert alert_texts.low_coverage_body("Leche", 4) == "Según tu consumo, Leche se agotará en 4 días."
    assert alert_texts.expiry_body("Yogur", 3) == "Yogur vence en 3 días."
    assert alert_texts.expiry_body("Yogur", 0) == "Yogur vence hoy."
    assert alert_texts.expiry_body("Yogur", 1) == "Yogur vence mañana."
    assert alert_texts.expiry_body("Yogur", -1) == "Yogur venció hace 1 día."
    assert alert_texts.expiry_body("Yogur", -4) == "Yogur venció hace 4 días."
    assert alert_texts.slow_pace_body("Miel", 1, 5) == "Al ritmo actual, 1 unidad de Miel vencerá en 5 días."
    assert alert_texts.slow_pace_body("Miel", 3, 1) == "Al ritmo actual, 3 unidades de Miel vencerán mañana."


def test_the_stock_messages_say_what_the_days_are_compared_to():
    assert "mínimo de 7" in alert_texts.understock_body("Fideos", 3, 7)
    assert "alcanza para 1 día," in alert_texts.understock_body("Fideos", 1, 7)
    assert "mínimo de 7" in alert_texts.overstock_body("Arroz", 90, 7)
