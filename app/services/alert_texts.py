"""Textos de los avisos (push y mail), en un solo lugar para que el job y los endpoints digan lo mismo."""


def when(days: int) -> str:
    """«hoy», «mañana» o «en N días»: nunca «en 0 días»."""
    if days <= 0:
        return "hoy"
    if days == 1:
        return "mañana"
    return f"en {days} días"


def _units(amount: int) -> str:
    return f"{amount} unidad" if amount == 1 else f"{amount} unidades"


def low_coverage_body(product: str, days: int) -> str:
    return f"Según tu consumo, {product} se agotará {when(days)}."


def expiry_body(product: str, days: int) -> str:
    if days < 0:
        ago = -days
        return f"{product} venció hace {ago} día{'s' if ago != 1 else ''}."
    return f"{product} vence {when(days)}."


def slow_pace_body(product: str, units: int, days: int) -> str:
    verb = "vencerá" if units == 1 else "vencerán"
    return f"Al ritmo actual, {_units(units)} de {product} {verb} {when(days)}."


def overstock_body(product: str, days: int, limit: int) -> str:
    return (
        f"Tenés {product} para unos {days} días, mucho más que tu mínimo de {limit}. Quizás compraste de más."
    )


def understock_body(product: str, days: int, limit: int) -> str:
    return (
        f"Aun con la compra, {product} te alcanza para {days} día{'s' if days != 1 else ''}, menos que tu mínimo de "
        f"{limit}. Considerá comprar más."
    )
