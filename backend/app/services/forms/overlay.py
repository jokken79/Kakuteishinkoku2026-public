"""Overlay de valores sobre el 様式 oficial del NTA — Fase 3B-4.

A diferencia de `pdf.py` (que DIBUJA una réplica del formulario), este módulo
estampa los valores calculados SOBRE el PDF oficial en blanco del 国税庁
(令和7年分), igual que hacen freee / 弥生 para el 郵送. El resultado es el
documento oficial real con los números del contribuyente, listo para imprimir y
presentar.

Mecánica:
    1. Capa de texto (reportlab) del MISMO tamaño que la página oficial, con la
       fuente CID japonesa ``HeiseiKakuGo-W5`` (sin .ttf externo → portable).
    2. Merge de esa capa sobre el 様式 oficial (pypdf).

Las coordenadas se expresan en sistema **top-left** (origen arriba-izquierda, Y
hacia abajo) — el mismo que devuelve `page.get_text(...)` de PyMuPDF con el que
se mapearon las casillas. La conversión a reportlab (bottom-left) es interna.

Los 様式 oficiales viven en ``app/services/forms/templates/`` (descargados de
nta.go.jp; ver README de esa carpeta).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

logger = logging.getLogger(__name__)

# Carpeta de los 様式 oficiales del NTA (PDF en blanco).
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Fuente CJK embebida de reportlab (idéntica a pdf.py; robusta para kanji).
_JP_FONT = "HeiseiKakuGo-W5"
_FONT_REGISTERED = False

# Ajuste fino GLOBAL (pt) de toda la capa, por si el calibrado lo necesita.
# Positivo en Y baja el texto (sistema top-left). Se afinó visualmente contra
# el render del 様式 oficial.
Y_FINE = 0.0
X_FINE = 0.0


def _ensure_font() -> str:
    """Registra (una vez) la fuente JP CID y devuelve su nombre."""
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(_JP_FONT))
        _FONT_REGISTERED = True
    return _JP_FONT


@dataclass(frozen=True)
class Field:
    """Un valor a estampar sobre el 様式 oficial.

    Args:
        text: Texto a dibujar (ya formateado).
        x: Coordenada X (pt, desde la izquierda).
        y: Coordenada Y en sistema **top-left** (pt, desde el borde superior).
        align: ``"r"`` (derecha, default para montos), ``"l"`` o ``"c"``.
        size: Tamaño de fuente (pt).
        tracking: Espaciado fijo entre caracteres (pt). Útil para importes
            dentro de las casillas cuadriculadas oficiales.
    """

    text: str
    x: float
    y: float
    align: str = "r"
    size: float = 9.5
    tracking: float | None = None


def _tracked_width(text: str, tracking: float) -> float:
    """Ancho visual entre centros de caracteres con espaciado fijo."""
    return max(len(text) - 1, 0) * tracking


def _draw_tracked(c: Canvas, f: Field, x: float, y: float) -> None:
    """Dibuja un `Field` usando espaciado fijo entre caracteres."""
    tracking = f.tracking
    if tracking is None:
        if f.align == "r":
            c.drawRightString(x, y, f.text)
        elif f.align == "c":
            c.drawCentredString(x, y, f.text)
        else:
            c.drawString(x, y, f.text)
        return

    width = _tracked_width(f.text, tracking)
    if f.align == "r":
        start_x = x - width
    elif f.align == "c":
        start_x = x - width / 2
    else:
        start_x = x
    for i, ch in enumerate(f.text):
        c.drawCentredString(start_x + i * tracking, y, ch)


def _draw_field_rotated90(c: Canvas, f: Field) -> None:
    """Dibuja un `Field` sobre una página con ``/Rotate 90`` (p. ej. 決算書).

    Las coords del `Field` están en el espacio VISUAL (rotado, top-left, 842×595)
    que reporta PyMuPDF. El 様式 se muestra rotado 90° CW desde un mediabox
    vertical (595×842). La capa se dibuja en ese mediabox sin rotar; para que el
    texto salga derecho y en su sitio tras el giro de pantalla se aplica la
    transformación inversa: ``px = vy``, ``py = vx`` con el texto rotado 90° CCW.
    Verificado empíricamente con marcadores en las 4 esquinas + centro.

    Args:
        c: Canvas de reportlab (tamaño = mediabox sin rotar).
        f: Campo a dibujar (coords visuales).
    """
    c.saveState()
    c.translate(f.y, f.x)  # px = vy, py = vx
    c.rotate(90)
    _draw_tracked(c, f, 0, 0)
    c.restoreState()


def _draw_layer(
    media_w: float,
    media_h: float,
    crop_left: float,
    crop_top: float,
    fields: list[Field],
    rotation: int = 0,
) -> PdfReader:
    """Crea una capa PDF de una página con los `fields` dibujados.

    Las coordenadas de los `Field` están en el sistema **top-left relativo al
    cropbox** (el mismo que devuelve PyMuPDF `page.get_text`, cuyo origen es la
    esquina superior-izquierda del área visible). El merge de pypdf, en cambio,
    opera en el sistema PDF nativo (bottom-left, origen del mediabox). Por eso la
    capa tiene el tamaño del MEDIABOX y la transformación incorpora el offset del
    cropbox:

        x_pdf = crop_left + f.x
        y_pdf = crop_top  − f.y   (baseline; reportlab dibuja hacia arriba)

    Sin este offset el texto sale desplazado (≈ el margen del cropbox).

    Args:
        media_w: Ancho del mediabox (pt).
        media_h: Alto del mediabox (pt).
        crop_left: Borde izquierdo del cropbox en coords PDF nativas.
        crop_top: Borde superior del cropbox en coords PDF nativas (bottom-left).
        fields: Valores a estampar.

    Returns:
        `PdfReader` de una sola página con la capa transparente.
    """
    font = _ensure_font()
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(media_w, media_h))
    for f in fields:
        if not f.text:
            continue
        c.setFont(font, f.size)
        if rotation == 90:
            _draw_field_rotated90(c, f)
            continue
        x = crop_left + f.x + X_FINE
        y = crop_top - f.y - Y_FINE
        _draw_tracked(c, f, x, y)
    c.save()
    buf.seek(0)
    return PdfReader(buf)


def render_overlay(
    template_name: str,
    page_fields: dict[int, list[Field]],
    *,
    keep_pages: list[int] | None = None,
) -> bytes:
    """Estampa los valores sobre un 様式 oficial y devuelve el PDF resultante.

    Args:
        template_name: Nombre del archivo en ``templates/`` (ej. ``"r07_01.pdf"``).
        page_fields: Mapa ``{índice_de_página: [Field, ...]}``. Las páginas sin
            entrada se copian del 様式 sin cambios.
        keep_pages: Si se indica, SOLO se incluyen esas páginas (en ese orden) en
            el PDF de salida. Útil para emitir 第一表＋第二表 (págs 0,1) sin las
            copias 控用 (págs 2,3).

    Returns:
        Bytes del PDF (様式 oficial + valores).

    Raises:
        FileNotFoundError: Si no existe el 様式 en ``templates/``.
    """
    path = _TEMPLATES_DIR / template_name
    if not path.is_file():
        raise FileNotFoundError(
            f"No se encontró el 様式 oficial '{template_name}' en {_TEMPLATES_DIR}. "
            "Descargalo de nta.go.jp (ver templates/README.md)."
        )
    base = PdfReader(str(path))
    writer = PdfWriter()
    indices = keep_pages if keep_pages is not None else list(range(len(base.pages)))
    # Asignar las páginas al writer ANTES de mergear (pypdf >=6 deprecó mergear
    # sobre páginas no asociadas a un writer).
    for idx in indices:
        writer.add_page(base.pages[idx])
    for out_i, idx in enumerate(indices):
        fields = page_fields.get(idx)
        if not fields:
            continue
        page = writer.pages[out_i]
        mediabox = page.mediabox
        cropbox = page.cropbox
        rotation = int(page.get("/Rotate", 0) or 0) % 360
        layer = _draw_layer(
            float(mediabox.width),
            float(mediabox.height),
            float(cropbox.left),
            float(cropbox.top),
            fields,
            rotation=rotation,
        )
        page.merge_page(layer.pages[0])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
