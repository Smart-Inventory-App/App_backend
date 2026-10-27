"""Cuánto conviene reponer de un producto para volver a la cobertura que el usuario configuró."""


def suggested_restock(daily_rate: float | None, coverage_days: int, stock: int) -> int:
    """Unidades a comprar para cubrir `coverage_days` días al ritmo de consumo actual (0 si no hace falta)."""
    if not daily_rate or daily_rate <= 0:
        return 0
    return max(0, round(daily_rate * coverage_days) - stock)
