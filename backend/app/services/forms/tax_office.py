"""税務署 / jurisdicción del 提出先 — Fase 3B-3.

Catálogo mínimo de 税務署 (oficinas tributarias) para el encabezado del
確定申告書. El formulario oficial lleva en su esquina superior la leyenda
「____税務署長」 con el NOMBRE de la oficina a la que se presenta — NO su
dirección (el PDF lleva el 納税地 del CONTRIBUYENTE, no el del 税務署).

La oficina se resuelve desde `Taxpayer.filing_office`. Si falta o no está en el
catálogo, se deja vacía para evitar atribuir una oficina no confirmada.

Fuente de los datos: research/06-formato-oficial-nta.md §4 (CONFIRMADO con el
手引き oficial 令和7 + página del 津島税務署 del 名古屋国税局).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaxOffice:
    """Datos de un 税務署 para el encabezado del 申告書.

    Args:
        key: Identificador estable (en inglés/romaji).
        header_name: Nombre que va antes de 「税務署長」 en el encabezado
            (ej. ``"津島"`` → "津島税務署長"). Es lo ÚNICO que aparece en el PDF.
        postal_code: 〒 de la oficina (referencia; NO va en el PDF del owner).
        tel: Teléfono de la oficina (referencia).
        national_bureau: 国税局 al que pertenece (referencia).
        jurisdiction: 管轄 (municipios cubiertos) — referencia / validación UI.
    """

    key: str
    header_name: str
    postal_code: str
    tel: str
    national_bureau: str
    jurisdiction: str

    @property
    def header_label(self) -> str:
        """Devuelve la leyenda completa del encabezado (「○○税務署長」)."""
        return f"{self.header_name}税務署長"


# Catálogo de oficinas conocidas (ampliable). Solo 津島 está CONFIRMADO en el
# research; agregar otras requiere confirmar 〒/管轄 oficiales antes de producción.
_OFFICES: dict[str, TaxOffice] = {
    "tsushima": TaxOffice(
        key="tsushima",
        header_name="津島",
        postal_code="496-8720",  # CONFIRMADO (research 06 §4).
        tel="0567-26-2161",  # CONFIRMADO.
        national_bureau="名古屋国税局",
        jurisdiction="津島市・愛西市・弥富市・あま市・海部郡（大治町・蟹江町・飛島村）",
    ),
}

_UNKNOWN = TaxOffice(
    key="", header_name="", postal_code="", tel="", national_bureau="", jurisdiction="",
)


def resolve_tax_office(office_key: str | None = None) -> TaxOffice:
    """Resuelve la oficina conocida; una clave ausente o desconocida queda vacía.

    Args:
        office_key: Clave de la oficina (`filing_office` del Taxpayer). Si es
            ``None`` o desconocida, no se atribuye ninguna oficina.

    Returns:
        El `TaxOffice` resuelto (nunca ``None``).
    """
    if office_key and office_key in _OFFICES:
        return _OFFICES[office_key]
    return _UNKNOWN
