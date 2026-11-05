"""Tests del módulo 過去の申告 (archivo histórico de declaraciones anteriores).

Cubren:
    - CRUD: subir / listar / editar / borrar un PDF de 確定申告 viejo.
    - Idempotencia por hash: subir el mismo PDF dos veces no duplica.
    - Extracción: un PDF generado con reportlab que simula un 申告書 viejo
      (con 所得/納付額/令和N年/税務署) se extrae correctamente.
    - Comparación año a año: la serie viene ordenada por año.
    - PDF: el endpoint /pdf devuelve el archivo archivado.

Usan SQLite en memoria + carpeta de archivo en `tmp_path` (no ensucian el repo).
"""

from __future__ import annotations

import io
import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base, Taxpayer

# Fuente CJK (TrueType) para que el TEXTO japonés del PDF de prueba sea
# recuperable por pymupdf (las CIDFont integradas de reportlab no llevan
# ToUnicode CMap, así que el japonés saldría como mojibake). Buscamos una de
# Windows; si no hay, los tests que dependen de extraer japonés se saltan
# (CI Linux sin fuentes JP). Los montos ASCII se extraen siempre.
_CJK_FONT_CANDIDATES = [
    # Windows (entorno del owner).
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\msmincho.ttc",
    # Linux (CI / contenedor). reportlab solo lee TrueType "glyf"; las Noto CJK
    # .ttc son CFF/OpenType y NO sirven. IPAex Gothic (TrueType) si: instalar con
    # `apt-get install fonts-ipaexfont` o descargar a ~/.fonts/ipaexg.ttf.
    os.path.expanduser("~/.fonts/ipaexg.ttf"),
    "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/takao-gothic/TakaoGothic.ttf",
]
_CJK_FONT_NAME = "TestJP"
_HAS_CJK_FONT = False
for _candidate in _CJK_FONT_CANDIDATES:
    if os.path.exists(_candidate):
        try:
            pdfmetrics.registerFont(TTFont(_CJK_FONT_NAME, _candidate, subfontIndex=0))
            _HAS_CJK_FONT = True
            break
        except Exception:  # noqa: BLE001 — probar el siguiente candidato.
            continue

requires_cjk_font = pytest.mark.skipif(
    not _HAS_CJK_FONT,
    reason="No hay fuente CJK TrueType (extracción de texto JP no testeable aquí).",
)


def _make_filing_pdf(
    *,
    reiwa_year: int = 6,
    income: int = 4_200_000,
    tax_paid: int | None = 185_300,
    tax_refund: int | None = None,
    office: str = "津島税務署",
) -> bytes:
    """Genera un PDF que simula un 申告書 viejo (texto seleccionable).

    Args:
        reiwa_year: Número del año 令和 (6 == 令和6年分 == 2024).
        income: 所得金額 a estampar.
        tax_paid: 納める税金, o ``None`` si es un año de 還付.
        tax_refund: 還付される税金, o ``None``.
        office: Nombre del 税務署.

    Returns:
        Bytes del PDF generado.
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    # Fuente CJK TrueType (con ToUnicode) para que pymupdf recupere el japonés.
    font = _CJK_FONT_NAME if _HAS_CJK_FONT else "Helvetica"
    text = c.beginText(40, 800)
    text.setFont(font, 11)
    lines = [
        "確定申告書B",
        f"令和{reiwa_year}年分の所得税及び復興特別所得税の申告書",
        office,
        f"所得金額の合計   {income:,}",
    ]
    if tax_paid is not None:
        lines.append(f"納める税金   {tax_paid:,}")
    if tax_refund is not None:
        lines.append(f"還付される税金   {tax_refund:,}")
    for line in lines:
        text.textLine(line)
    c.drawText(text)
    c.showPage()
    c.save()
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    """Cliente con BD SQLite en memoria, un Taxpayer y archivo en tmp_path."""
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    session: Session = factory()
    session.add(Taxpayer(name="過去 太郎"))
    session.commit()
    session.close()

    def _override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    get_settings.cache_clear()
    settings = get_settings()
    settings.past_filings_dir = str(tmp_path / "past_filings")

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _upload(client: TestClient, pdf: bytes, *, year: int | None = None) -> dict:
    """Sube un PDF y devuelve el body de la respuesta."""
    data = {"year": str(year)} if year is not None else {}
    resp = client.post(
        "/api/v1/past-filings",
        files={"file": ("kakutei.pdf", pdf, "application/pdf")},
        data=data,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Subida + extracción ---------------------------------------------------


@requires_cjk_font
def test_upload_extracts_amounts(client: TestClient) -> None:
    """Subir un 申告書 viejo extrae 所得/納付額/年度/税務署 del texto del PDF."""
    body = _upload(client, _make_filing_pdf())
    assert body["duplicate"] is False
    assert body["extracted"] is True
    filing = body["filing"]
    assert filing["year"] == 2024  # 令和6年 == 2024
    assert filing["total_income"] == 4_200_000
    assert filing["tax_paid"] == 185_300
    assert filing["tax_office"] == "津島税務署"
    assert filing["extraction_source"] == "auto"


@requires_cjk_font
def test_upload_refund_year(client: TestClient) -> None:
    """Un año de 還付 extrae el monto de devolución (sin 納付額)."""
    pdf = _make_filing_pdf(reiwa_year=5, income=3_100_000, tax_paid=None, tax_refund=42_800)
    filing = _upload(client, pdf)["filing"]
    assert filing["year"] == 2023
    assert filing["tax_refund"] == 42_800
    assert filing["tax_paid"] is None


def test_upload_year_from_form_overrides(client: TestClient) -> None:
    """El year del form tiene prioridad sobre el detectado del PDF."""
    filing = _upload(client, _make_filing_pdf(reiwa_year=6), year=2022)["filing"]
    assert filing["year"] == 2022


def test_upload_empty_file_400(client: TestClient) -> None:
    """Un archivo vacío devuelve 400."""
    resp = client.post(
        "/api/v1/past-filings",
        files={"file": ("x.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


def test_upload_non_pdf_400(client: TestClient) -> None:
    """Un archivo que no es PDF (sin cabecera %PDF) devuelve 400."""
    resp = client.post(
        "/api/v1/past-filings",
        files={"file": ("x.pdf", b"esto no es un pdf", "application/pdf")},
        data={"year": "2024"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "not_pdf"


def test_upload_unknown_year_422(client: TestClient) -> None:
    """Un PDF sin 令和N年 ni year en el form devuelve 422 (year requerido)."""
    # PDF mínimo sin texto de año detectable.
    minimal = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    resp = client.post(
        "/api/v1/past-filings",
        files={"file": ("x.pdf", minimal, "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "year_required"


# --- Idempotencia ----------------------------------------------------------


def test_upload_idempotent_by_hash(client: TestClient) -> None:
    """Subir el mismo PDF dos veces NO duplica (idempotencia por hash)."""
    pdf = _make_filing_pdf()
    first = _upload(client, pdf, year=2024)
    second = _upload(client, pdf, year=2024)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["filing"]["id"] == second["filing"]["id"]

    listed = client.get("/api/v1/past-filings").json()
    assert len(listed["filings"]) == 1


# --- Listado + comparación -------------------------------------------------


@requires_cjk_font
def test_list_and_comparison_series(client: TestClient) -> None:
    """Listar varios años devuelve la serie año a año ordenada ascendente."""
    _upload(client, _make_filing_pdf(income=3_000_000, tax_paid=120_000), year=2022)
    _upload(client, _make_filing_pdf(income=3_500_000, tax_paid=150_000), year=2023)
    _upload(client, _make_filing_pdf(income=4_200_000, tax_paid=185_300), year=2024)

    body = client.get("/api/v1/past-filings").json()
    # Registros ordenados por año descendente.
    assert [f["year"] for f in body["filings"]] == [2024, 2023, 2022]
    # Serie de comparación ordenada ascendente.
    years = [p["year"] for p in body["comparison"]]
    assert years == [2022, 2023, 2024]
    # net_tax positivo (納付) para los tres.
    assert all(p["net_tax"] > 0 for p in body["comparison"])


# --- Edición ---------------------------------------------------------------


def test_patch_corrects_amounts(client: TestClient) -> None:
    """PATCH corrige montos y marca el registro como 'manual'."""
    filing = _upload(client, _make_filing_pdf(), year=2024)["filing"]
    patch = client.patch(
        f"/api/v1/past-filings/{filing['id']}",
        json={"total_income": 9_999_999, "tax_office": "名古屋中税務署"},
    )
    assert patch.status_code == 200
    updated = patch.json()
    assert updated["total_income"] == 9_999_999
    assert updated["tax_office"] == "名古屋中税務署"
    assert updated["extraction_source"] == "manual"


def test_patch_not_found_404(client: TestClient) -> None:
    """PATCH de un id inexistente devuelve 404."""
    resp = client.patch(
        "/api/v1/past-filings/00000000-0000-0000-0000-000000000000",
        json={"total_income": 1},
    )
    assert resp.status_code == 404


# --- Borrado ---------------------------------------------------------------


def test_delete_removes_record(client: TestClient) -> None:
    """DELETE elimina el registro y desaparece del listado."""
    filing = _upload(client, _make_filing_pdf(), year=2024)["filing"]
    delete = client.delete(f"/api/v1/past-filings/{filing['id']}")
    assert delete.status_code == 204
    listed = client.get("/api/v1/past-filings").json()
    assert listed["filings"] == []


# --- PDF -------------------------------------------------------------------


def test_get_pdf_returns_archived_file(client: TestClient) -> None:
    """GET /{id}/pdf devuelve el PDF original archivado."""
    pdf = _make_filing_pdf()
    filing = _upload(client, pdf, year=2024)["filing"]
    resp = client.get(f"/api/v1/past-filings/{filing['id']}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


# --- Parser unitario (independiente del render del PDF) --------------------


def test_parser_extracts_from_raw_text() -> None:
    """El parser de montos funciona sobre el texto crudo (sin depender del PDF).

    Cubre la lógica de regex de `extract_text`/regex con texto japonés directo,
    así está testeada aunque no haya fuente CJK para generar el PDF.
    """
    from app.services.past_filings.extractor import (
        _INCOME_RES,
        _TAX_PAID_RES,
        _TAX_REFUND_RES,
        _first_match,
        _parse_year,
    )

    text = (
        "令和6年分の所得税及び復興特別所得税の申告書\n"
        "津島税務署\n"
        "所得金額の合計   4,200,000\n"
        "納める税金   185,300\n"
    )
    assert _parse_year(text) == 2024
    assert _first_match(text, _INCOME_RES) == 4_200_000
    assert _first_match(text, _TAX_PAID_RES) == 185_300
    assert _first_match(text, _TAX_REFUND_RES) is None

    refund_text = "令和元年分\n還付される税金   42,800\n"
    assert _parse_year(refund_text) == 2019
    assert _first_match(refund_text, _TAX_REFUND_RES) == 42_800
