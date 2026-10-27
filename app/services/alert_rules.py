"""Reglas de las alertas en un solo lugar: de dónde sale cada límite y cuándo una alerta es crítica o advertencia.

Hay dos reglas que configura el usuario, en su perfil (valen para todos sus productos) y, si quiere, en cada producto
(la del producto manda sobre la del perfil):

- **Vencimiento**: días de anticipación. Se alerta cuando faltan esos días o menos para que venza (o ya venció).
- **Stock mínimo**: días de cobertura. Se alerta cuando, al ritmo de consumo que calcula el modelo predictivo, el stock
  alcanza para menos de esos días.

Para las dos vale el mismo criterio de nivel:

- **crítica**: ya se llegó al límite (o se lo pasó);
- **advertencia**: se está cerca del límite, dentro de un margen que depende de él;
- sin alerta: está lejos.
"""
import math
from datetime import date

from app.models.profile import DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO

# "Cerca" del límite es hasta la mitad de ese límite más allá (con un mínimo de 2 días)
NEAR_RATIO = 0.5
MIN_NEAR_DAYS = 2

SCOPE_PRODUCT = "product"
SCOPE_GENERAL = "general"


def near_margin(limit: int) -> int:
    """Cuántos días más allá del límite todavía se considera "cerca"."""
    return max(MIN_NEAR_DAYS, math.ceil(limit * NEAR_RATIO))


def resolve_limit(own: int | None, general: int | None, default: int) -> tuple[int, str]:
    """El límite que rige y de dónde sale: la regla propia del producto, la general del perfil o la de fábrica."""
    if own:
        return own, SCOPE_PRODUCT
    if general:
        return general, SCOPE_GENERAL
    return default, SCOPE_GENERAL


def expiry_limit(product_days: int | None, profile) -> tuple[int, str]:
    general = getattr(profile, "dias_alerta_vencimiento", None)
    return resolve_limit(product_days, general, DEFAULT_DIAS_ALERTA_VENCIMIENTO)


def coverage_limit(product_days: int | None, profile) -> tuple[int, str]:
    general = getattr(profile, "stock_minimo", None)
    return resolve_limit(product_days, general, DEFAULT_COVERAGE_DAYS)


def expiry_level(days_to_expiry: int, limit: int) -> str | None:
    """Crítica si faltan `limit` días o menos (o ya venció); advertencia si está un poco más lejos; si no, nada."""
    if days_to_expiry <= limit:
        return "critical"
    if days_to_expiry <= limit + near_margin(limit):
        return "warning"
    return None


def coverage_level(days_until_stockout: int | None, limit: int) -> str | None:
    """Crítica si el stock alcanza para menos de `limit` días; advertencia si está cerca de ese mínimo; si no, nada."""
    if days_until_stockout is None:
        return None
    if days_until_stockout < limit:
        return "critical"
    if days_until_stockout < limit + near_margin(limit):
        return "warning"
    return None


def days_until(expiry: date, today: date | None = None) -> int:
    return (expiry - (today or date.today())).days


def whole_days(value) -> int | None:
    """Los días que calcula el modelo pueden venir con decimales: se redondean. Nunca son negativos."""
    if value is None:
        return None
    return max(0, round(value))
