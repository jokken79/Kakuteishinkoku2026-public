"""Tests del servicio de importacion de XML de 控除証明書 (Nivel 2 e-Tax).

Cubre el parser (detección de tipo por root, extracción de montos por XPath del
schema, fórmula escalonada del 生命保険, conversión 元号->西暦, degradación con
gracia) y los endpoints (preview sin persistir, commit crea/actualiza Deduction).

Los XML de muestra se construyen MÍNIMOS pero válidos a partir del
`koujo_schema.json`, con el namespace compartido del NTA en el root.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import create_app
from app.models.entities import Deduction, FiscalYear, Taxpayer
from app.models.enums import (
    DeductionType,
    FilingType,
    FiscalYearStatus,
)
from app.services.import_xml.koujo_parser import (
    KoujoParseError,
    _category_deduction,
    _new_system_amount,
    _old_system_amount,
    parse_koujo_xml,
)

_NS = "http://xml.e-tax.nta.go.jp/XSD/kyotsu"


# --- Builders de XML de muestra (mínimos válidos) --------------------------


def _seimei_xml(*, new_ippan: int = 0, new_kaigo: int = 0, new_nenkin: int = 0,
                old_ippan: int = 0, old_nenkin: int = 0) -> bytes:
    """生命保険料控除証明書 (TEG800) con montos 差引保険料 por categoría."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEG800 xmlns="{_NS}" VR="1.1">
  <WCA00000>テスト生命保険株式会社</WCA00000>
  <WCC00000><yyyy>2025</yyyy><mm>10</mm><dd>15</dd></WCC00000>
  <WCD00000>確定 太郎</WCD00000>
  <WCE00000>
    <WCE00010><yyyy>2025</yyyy></WCE00010>
    <WCE00020>終身保険</WCE00020>
    <WCE00190>
      <WCE00220>
        <WCE00230><WCE00260>{old_ippan}</WCE00260></WCE00230>
        <WCE00270><WCE00300>{old_nenkin}</WCE00300></WCE00270>
      </WCE00220>
      <WCE00310>
        <WCE00320><WCE00350>{new_ippan}</WCE00350></WCE00320>
        <WCE00360><WCE00390>{new_kaigo}</WCE00390></WCE00360>
        <WCE00400><WCE00430>{new_nenkin}</WCE00430></WCE00400>
      </WCE00310>
    </WCE00190>
  </WCE00000>
</TEG800>""".encode()


def _jishin_xml(*, earthquake: int = 0, old_longterm: int = 0) -> bytes:
    """地震保険料控除証明書 (TEG810)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEG810 xmlns="{_NS}" VR="1.1">
  <WDA00000>テスト損害保険株式会社</WDA00000>
  <WDC00000><yyyy>2025</yyyy><mm>11</mm><dd>1</dd></WDC00000>
  <WDD00000>確定 太郎</WDD00000>
  <WDE00000>
    <WDE00010><yyyy>2025</yyyy></WDE00010>
    <WDE00160><WDE00180>{earthquake}</WDE00180></WDE00160>
    <WDE00190><WDE00210>{old_longterm}</WDE00210></WDE00190>
  </WDE00000>
</TEG810>""".encode()


def _ideco_xml(*, total: int | None = 240000, paid: int = 200000,
               scheduled: int = 40000) -> bytes:
    """小規模企業共済等掛金控除証明書 (TEG850), año en 元号 (令和7)."""
    total_block = f"<WPI00000>{total}</WPI00000>" if total is not None else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEG850 xmlns="{_NS}" VR="1.0">
  <WPA00000><era>5</era><yy>7</yy></WPA00000>
  <WPB00000><kubun_CD>2</kubun_CD></WPB00000>
  <WPC00000>確定 太郎</WPC00000>
  <WPE00000>1234567890</WPE00000>
  <WPF00000><era>5</era><yy>7</yy></WPF00000>
  <WPG00000><WPG00020>{paid}</WPG00020></WPG00000>
  <WPH00000><WPH00030>{scheduled}</WPH00030></WPH00000>
  {total_block}
</TEG850>""".encode()


def _kokumin_nenkin_xml(*, total: int | None = 200000, paid: int = 180000,
                        estimated: int = 20000) -> bytes:
    """国民年金保険料等控除証明書 (TEG840), año en 元号."""
    total_block = f"<WOM00000>{total}</WOM00000>" if total is not None else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEG840 xmlns="{_NS}" VR="1.0">
  <WOA00000><kubun_CD>1</kubun_CD></WOA00000>
  <WOC00000><era>5</era><yy>7</yy></WOC00000>
  <WOE00000>確定 太郎</WOE00000>
  <WOK00000>{paid}</WOK00000>
  <WOL00000>{estimated}</WOL00000>
  {total_block}
</TEG840>""".encode()


def _furusato_multi_xml(*amounts: int) -> bytes:
    """寄附金受領証明書 複数 (TEG821) con N donaciones."""
    rows = "\n".join(
        f"""  <WHB00000>
    <WHB00010>R-{i}</WHB00010>
    <WHB00020><kubun_CD>7</kubun_CD></WHB00020>
    <WHB00050>{amt}</WHB00050>
    <WHB00060><yyyy>2025</yyyy><mm>12</mm><dd>20</dd></WHB00060>
    <WHB00070>テスト市役所</WHB00070>
  </WHB00000>"""
        for i, amt in enumerate(amounts, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEG821 xmlns="{_NS}" VR="1.1">
  <WHA00000>確定 太郎</WHA00000>
{rows}
</TEG821>""".encode()


# --- Tests de la fórmula 生命保険 (unitarios) ------------------------------


def test_new_system_amount_brackets() -> None:
    """Tabla 新制度: tramos escalonados con tope ¥40,000."""
    assert _new_system_amount(0) == 0
    assert _new_system_amount(20_000) == 20_000  # <= 20k -> todo
    assert _new_system_amount(40_000) == 30_000  # 40000/2 + 10000
    assert _new_system_amount(80_000) == 40_000  # 80000/4 + 20000
    assert _new_system_amount(200_000) == 40_000  # tope


def test_old_system_amount_brackets() -> None:
    """Tabla 旧制度: tramos escalonados con tope ¥50,000."""
    assert _old_system_amount(25_000) == 25_000
    assert _old_system_amount(50_000) == 37_500  # 50000/2 + 12500
    assert _old_system_amount(100_000) == 50_000  # 100000/4 + 25000
    assert _old_system_amount(300_000) == 50_000  # tope


def test_category_deduction_combines_new_and_old() -> None:
    """一般/年金 con 新+旧: el mayor entre 新, 旧, y (新+旧) topado a 40,000."""
    # new=80000 -> 40000; old=100000 -> 50000; combinado topado a 40000 -> 40000.
    # max(50000, 40000, 40000) = 50000 (旧 solo ya es 50000).
    assert _category_deduction(100_000, 80_000) == 50_000
    # Solo 新.
    assert _category_deduction(None, 40_000) == 30_000


# --- Tests del parser: detección y extracción ------------------------------


def test_parse_seimei_computes_deduction() -> None:
    """TEG800: calcula el 控除額 desde montos por categoría con la fórmula NTA."""
    # 一般新 80000 -> 40000; 介護医療新 40000 -> 30000; 個人年金新 20000 -> 20000.
    # Total = 90000 (< tope 120000).
    res = parse_koujo_xml(
        _seimei_xml(new_ippan=80_000, new_kaigo=40_000, new_nenkin=20_000)
    )
    assert res.deduction_type == DeductionType.SEIMEI_HOKEN
    assert res.root_element == "TEG800"
    assert res.amount == 90_000
    assert res.issuer == "テスト生命保険株式会社"
    assert res.year == 2025
    assert res.needs_confirmation is False
    cats = {c["category"]: c["deduction"] for c in res.details["categories"]}
    assert cats == {"ippan": 40_000, "kaigo_iryo": 30_000, "nenkin": 20_000}


def test_parse_seimei_global_cap() -> None:
    """TEG800: el 控除額 total se acota al tope global ¥120,000."""
    res = parse_koujo_xml(
        _seimei_xml(new_ippan=200_000, new_kaigo=200_000, new_nenkin=200_000)
    )
    # 40000 * 3 = 120000 (justo el tope).
    assert res.amount == 120_000


def test_parse_seimei_empty_needs_confirmation() -> None:
    """TEG800 sin montos: monto 0 y requiere confirmación (no inventa)."""
    res = parse_koujo_xml(_seimei_xml())
    assert res.amount == 0
    assert res.needs_confirmation is True


def test_parse_jishin_direct_amount() -> None:
    """TEG810: el 控除対象保険料 es directo (地震 + 旧長期)."""
    res = parse_koujo_xml(_jishin_xml(earthquake=30_000, old_longterm=5_000))
    assert res.deduction_type == DeductionType.JISHIN_HOKEN
    assert res.amount == 35_000
    assert res.needs_confirmation is False


def test_parse_ideco_total_direct() -> None:
    """TEG850: WPI00000 (控除合計額) es directo; año 元号 -> 西暦."""
    res = parse_koujo_xml(_ideco_xml(total=240_000))
    assert res.deduction_type == DeductionType.IDECO
    assert res.amount == 240_000
    assert res.year == 2025  # 令和7 = 2018 + 7
    assert res.needs_confirmation is False


def test_parse_ideco_fallback_to_paid() -> None:
    """TEG850 sin 控除合計額: cae a 払込済額 + 予定額 y pide confirmación."""
    res = parse_koujo_xml(_ideco_xml(total=None, paid=200_000, scheduled=40_000))
    assert res.amount == 240_000
    assert res.needs_confirmation is True


def test_parse_kokumin_nenkin_to_shakai_hoken() -> None:
    """TEG840: el 国民年金 alimenta el 社会保険料控除 (合計額 directo)."""
    res = parse_koujo_xml(_kokumin_nenkin_xml(total=200_000))
    assert res.deduction_type == DeductionType.SHAKAI_HOKEN
    assert res.amount == 200_000
    assert res.year == 2025


def test_parse_furusato_sums_donations() -> None:
    """TEG821: suma todas las donaciones del archivo (FURUSATO)."""
    res = parse_koujo_xml(_furusato_multi_xml(10_000, 20_000, 5_000))
    assert res.deduction_type == DeductionType.FURUSATO
    assert res.amount == 35_000
    assert res.needs_confirmation is False


# --- Tests del parser: degradación con gracia ------------------------------


def test_parse_empty_raises() -> None:
    """Un XML vacío lanza KoujoParseError(empty_file)."""
    with pytest.raises(KoujoParseError) as exc:
        parse_koujo_xml(b"")
    assert exc.value.code == "empty_file"


def test_parse_invalid_xml_raises() -> None:
    """Un XML malformado lanza KoujoParseError(invalid_xml)."""
    with pytest.raises(KoujoParseError) as exc:
        parse_koujo_xml(b"<not-closed>")
    assert exc.value.code == "invalid_xml"


def test_parse_rejects_xml_entities() -> None:
    """El XML importado no expande DTD/entidades externas."""
    data = f"""<!DOCTYPE TEG999 [
<!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<TEG999 xmlns="{_NS}">&xxe;</TEG999>""".encode()
    with pytest.raises(KoujoParseError) as exc:
        parse_koujo_xml(data)
    assert exc.value.code == "invalid_xml"


def test_parse_unknown_type_raises() -> None:
    """Un root desconocido lanza KoujoParseError(unknown_koujo_type)."""
    with pytest.raises(KoujoParseError) as exc:
        parse_koujo_xml(f'<TEG999 xmlns="{_NS}"/>'.encode())
    assert exc.value.code == "unknown_koujo_type"


# --- Tests de endpoints: preview vs commit ---------------------------------


@pytest.fixture
def client(engine: Engine, session: Session) -> TestClient:
    """TestClient con un 年度 2025 sembrado y la sesion del fixture inyectada."""
    taxpayer = Taxpayer(name="確定 太郎", filing_type=FilingType.AOIRO_65)
    session.add(taxpayer)
    session.flush()
    fy = FiscalYear(
        taxpayer_id=taxpayer.id,
        year=2025,
        rules_ref="2025",
        status=FiscalYearStatus.OPEN,
    )
    session.add(fy)
    session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _upload(client: TestClient, data: bytes):
    """Helper: POST multipart con el XML adjunto al preview."""
    files = {"file": ("shomei.xml", data, "text/xml")}
    return client.post("/api/v1/deductions/import-xml/preview", files=files)


def test_preview_seimei_returns_amount(client: TestClient) -> None:
    """El preview de un 生命保険 XML devuelve tipo + 控除額 + desglose, sin persistir."""
    resp = _upload(client, _seimei_xml(new_ippan=80_000, new_kaigo=40_000))
    assert resp.status_code == 200
    body = resp.json()
    assert body["deduction_type"] == "seimei_hoken"
    assert body["amount"] == 70_000  # 40000 + 30000
    assert body["koujo_type"] == "生命保険料控除証明書"
    assert len(body["seimei_categories"]) == 3
    assert body["already_registered"] is False


def test_preview_does_not_persist(client: TestClient, session: Session) -> None:
    """El preview NO crea Deductions."""
    _upload(client, _ideco_xml())
    assert session.query(Deduction).count() == 0


def test_preview_unknown_type_400(client: TestClient) -> None:
    """Un XML de tipo no soportado devuelve 400 con código de dominio."""
    resp = _upload(client, f'<TEG999 xmlns="{_NS}"/>'.encode())
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unknown_koujo_type"


def test_commit_creates_deduction(client: TestClient, session: Session) -> None:
    """El commit crea la Deduction con el monto confirmado."""
    resp = client.post(
        "/api/v1/deductions/import-xml/commit",
        json={
            "deduction_type": "ideco",
            "amount": 240_000,
            "issuer": "確定 太郎",
            "year": 2025,
            "koujo_type": "小規模企業共済等掛金控除証明書",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    assert body["type"] == "ideco"
    assert body["amount"] == 240_000

    ded = session.scalars(
        select(Deduction).where(Deduction.type == DeductionType.IDECO)
    ).first()
    assert ded is not None
    assert ded.amount == 240_000
    assert ded.meta["source"] == "koujo_xml"


def test_commit_accumulates_existing(client: TestClient, session: Session) -> None:
    """Un 2do certificado del mismo tipo SUMA al monto existente."""
    payload = {"deduction_type": "seimei_hoken", "amount": 40_000}
    first = client.post("/api/v1/deductions/import-xml/commit", json=payload).json()
    assert first["created"] is True
    assert first["amount"] == 40_000

    second = client.post("/api/v1/deductions/import-xml/commit", json=payload).json()
    assert second["created"] is False
    assert second["amount"] == 80_000  # 40000 + 40000

    assert (
        session.query(Deduction)
        .filter(Deduction.type == DeductionType.SEIMEI_HOKEN)
        .count()
        == 1
    )


def test_commit_appears_in_deductions_list(client: TestClient) -> None:
    """La 控除 importada por XML aparece en GET /deductions."""
    client.post(
        "/api/v1/deductions/import-xml/commit",
        json={"deduction_type": "jishin_hoken", "amount": 30_000},
    )
    listing = client.get("/api/v1/deductions?year=2025").json()
    types = {d["type"] for d in listing["deductions"]}
    assert "jishin_hoken" in types
