"""Estadística mínima para muestras chicas: intervalo de confianza de Wilson para una proporción.

Se usa Wilson y no el intervalo normal («p ± 1,96·√(p(1−p)/n)») porque este último, con n pequeño o
una proporción cerca de 0 o 1, da intervalos de ancho cero o que se salen de [0, 1]. Wilson no.

**Límite que hay que decir siempre:** el intervalo supone observaciones independientes. Las
repeticiones del mismo caso no lo son, así que, con repeticiones, el intervalo es OPTIMISTA (más
angosto de lo que corresponde).
"""

from __future__ import annotations

from math import sqrt

#: Cuantil 0,975 de la normal estándar (95 % a dos colas).
Z_95 = 1.959963984540054


def wilson(aciertos: int, total: int, z: float = Z_95) -> tuple[float, float] | None:
    """Intervalo de Wilson para `aciertos` de `total`. `None` si `total` es 0 (sin dato)."""
    if total <= 0:
        return None
    if not 0 <= aciertos <= total:
        raise ValueError(f"aciertos ({aciertos}) debe estar entre 0 y total ({total})")
    p = aciertos / total
    denominador = 1 + z * z / total
    centro = (p + z * z / (2 * total)) / denominador
    mitad = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominador
    # Los extremos son exactos: 0 aciertos tiene límite inferior 0 y todos, límite superior 1; el
    # redondeo de la coma flotante daba 5e-17 y dejaba la proporción fuera del intervalo.
    inferior = 0.0 if aciertos == 0 else max(0.0, centro - mitad)
    superior = 1.0 if aciertos == total else min(1.0, centro + mitad)
    return inferior, superior


def texto_intervalo(intervalo: tuple[float, float] | None) -> str | None:
    """`0,62 – 0,91`, con coma decimal. `None` (sin dato) queda vacío, no «0 – 0»."""
    if intervalo is None:
        return None
    return f"{intervalo[0]:.2f} – {intervalo[1]:.2f}".replace(".", ",")
