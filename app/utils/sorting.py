import unicodedata


def alphabetical_key(text: str) -> str:
    """Clave para ordenar texto alfabéticamente sin que importen mayúsculas, minúsculas ni tildes.

    Así "ana", "Ana" y "Álvaro" quedan en el orden de un diccionario y no con todas las
    mayúsculas antes que las minúsculas. La "ñ" se ordena como letra propia, después de la "n",
    como en español.
    """
    folded = (text or "").casefold().replace("\u00f1", "n\uffff")
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(char for char in decomposed if not unicodedata.combining(char))
