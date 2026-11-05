"""Tests del servicio de importacion de CSV de banco/tarjeta (Fase 4-1).

Cubre el parser (encoding UTF-8/SHIFT-JIS, deteccion de columnas, filtro de
gastos, auto-勘定科目, idempotencia) y los endpoints (preview vs commit, dedup
contra BD, integracion con la bandeja de 仕訳).
"""

from __future__ import annotations

import datetime
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import create_app
from app.models.entities import FiscalYear, Taxpayer, Transaction
from app.models.enums import FilingType, FiscalYearStatus, TransactionSource
from app.seed.accounts import seed_accounts
from app.services.import_csv.builder import build_proposal
from app.services.import_csv.parser import (
    ColumnMapping,
    detect_columns,
    parse_csv,
    row_dedup_hash,
    sniff_decode,
)

# --- Fixtures de datos CSV -------------------------------------------------

# Extracto generico con columnas 取引日 / 摘要 / 出金金額 / 入金金額.
_CSV_ROWS = [
    ["取引日", "摘要", "出金金額", "入金金額", "残高"],
    ["2025/01/12", "セブンイレブン 新宿店", "1,280", "", "482,150"],
    ["2025/02/03", "アマゾンジャパン", "3,480", "", "478,670"],
    ["2025/02/15", "給与振込", "", "320,000", "798,670"],  # ingreso -> descartar
    ["2025/03/01", "ＮＴＴドコモ 携帯料金", "8,778", "", "789,892"],
    ["2025/04/12", "紀伊國屋書店 新宿本店", "3,740", "", "786,152"],
]


def _csv_bytes(encoding: str = "utf-8") -> bytes:
    """Serializa `_CSV_ROWS` a bytes en el encoding pedido."""
    buf = io.StringIO()
    import csv as _csv

    writer = _csv.writer(buf)
    writer.writerows(_CSV_ROWS)
    return buf.getvalue().encode(encoding)


@pytest.fixture
def today() -> datetime.date:
    """Fecha de referencia fija (futuro respecto al CSV) para los tests."""
    return datetime.date(2026, 1, 1)


# --- Tests del parser: encoding -------------------------------------------


def test_sniff_decode_utf8() -> None:
    """UTF-8 se decodifica y se reporta como tal."""
    text, enc = sniff_decode(_csv_bytes("utf-8"))
    assert "セブンイレブン" in text
    assert enc in ("utf-8", "utf-8-sig")


def test_sniff_decode_shift_jis() -> None:
    """SHIFT-JIS (cp932) se decodifica correctamente."""
    text, enc = sniff_decode(_csv_bytes("shift_jis"))
    assert "セブンイレブン" in text
    assert enc in ("cp932", "shift_jis")


def test_parse_csv_utf8_and_sjis_equivalent(today: datetime.date) -> None:
    """El parseo da las mismas filas en UTF-8 y en SHIFT-JIS."""
    res_utf8 = parse_csv(_csv_bytes("utf-8"), today=today)
    res_sjis = parse_csv(_csv_bytes("shift_jis"), today=today)
    assert [r.vendor for r in res_utf8.importable] == [
        r.vendor for r in res_sjis.importable
    ]
    assert [r.amount for r in res_utf8.importable] == [
        r.amount for r in res_sjis.importable
    ]


# --- Tests del parser: deteccion de columnas ------------------------------


def test_detect_columns_debit_credit() -> None:
    """Detecta 取引日/摘要/出金/入金 por sus headers."""
    mapping = detect_columns(["取引日", "摘要", "出金金額", "入金金額", "残高"])
    assert mapping.date == 0
    assert mapping.vendor == 1
    assert mapping.debit == 2
    assert mapping.credit == 3
    assert mapping.is_usable


def test_detect_columns_signed_amount() -> None:
    """Detecta una columna de monto generica (利用金額) con signo."""
    mapping = detect_columns(["利用日", "利用店名", "利用金額"])
    assert mapping.date == 0
    assert mapping.vendor == 1
    assert mapping.amount == 2
    assert mapping.debit is None
    assert mapping.is_usable


def test_detect_columns_english_headers() -> None:
    """Detecta headers en ingles (date/description/amount)."""
    mapping = detect_columns(["Date", "Description", "Amount"])
    assert mapping.date == 0
    assert mapping.vendor == 1
    assert mapping.amount == 2


def test_detect_columns_unusable_when_no_date() -> None:
    """Sin columna de fecha, el mapeo no es usable."""
    mapping = detect_columns(["店名", "メモ"])
    assert not mapping.is_usable


# --- Tests del parser: filtro de gastos -----------------------------------


def test_parse_filters_expenses_only(today: datetime.date) -> None:
    """Solo se importan gastos (debitos); el ingreso (入金) se descarta."""
    res = parse_csv(_csv_bytes("utf-8"), today=today)
    assert len(res.rows) == 5
    importable = res.importable
    assert len(importable) == 4
    vendors = [r.vendor for r in importable]
    assert "給与振込" not in vendors  # ingreso descartado
    skipped = [r for r in res.rows if not r.is_importable]
    assert any("入金" in (r.skipped_reason or "") for r in skipped)


def test_parse_signed_amount_negative_is_expense(today: datetime.date) -> None:
    """En columna con signo, negativo = gasto, positivo = ingreso (descartado)."""
    rows = [
        ["利用日", "利用店名", "利用金額"],
        ["2025/05/01", "コンビニ", "-540"],
        ["2025/05/02", "返金", "1000"],
    ]
    buf = io.StringIO()
    import csv as _csv

    _csv.writer(buf).writerows(rows)
    res = parse_csv(buf.getvalue().encode("utf-8"), today=today)
    assert len(res.importable) == 1
    assert res.importable[0].vendor == "コンビニ"
    assert res.importable[0].amount == 540


def test_parse_future_date_skipped(today: datetime.date) -> None:
    """Una fila con fecha futura no produce fecha valida (se descarta)."""
    rows = [
        ["取引日", "摘要", "出金金額"],
        ["2030/01/01", "未来の店", "1,000"],
    ]
    buf = io.StringIO()
    import csv as _csv

    _csv.writer(buf).writerows(rows)
    res = parse_csv(buf.getvalue().encode("utf-8"), today=today)
    assert len(res.importable) == 0


# --- Tests del parser: auto-勘定科目 ---------------------------------------


def test_auto_account_classification(today: datetime.date) -> None:
    """El 勘定科目 se sugiere por vendor (reusa classify_vendor)."""
    res = parse_csv(_csv_bytes("utf-8"), today=today)
    by_vendor = {r.vendor: build_proposal(r).account_code for r in res.importable}
    assert by_vendor["アマゾンジャパン"] == "502"  # 消耗品費
    assert by_vendor["ＮＴＴドコモ 携帯料金"] == "505"  # 通信費
    assert by_vendor["紀伊國屋書店 新宿本店"] == "506"  # 新聞図書費


def test_proposal_journal_balanced(today: datetime.date) -> None:
    """El 仕訳 candidato esta balanceado (Σ借方 = Σ貸方) con 事業主借 al credito."""
    res = parse_csv(_csv_bytes("utf-8"), today=today)
    row = res.importable[0]
    prop = build_proposal(row)
    debit = sum(ln.amount for ln in prop.journal.lines if ln.side == "debit")
    credit = sum(ln.amount for ln in prop.journal.lines if ln.side == "credit")
    assert debit == credit == row.amount
    credit_accounts = [
        ln.account_code for ln in prop.journal.lines if ln.side == "credit"
    ]
    assert credit_accounts == ["312"]  # 事業主借


def test_proposal_tax_lines_decompose(today: datetime.date) -> None:
    """El total 税込 se descompone en base + 消費税 al 10%."""
    res = parse_csv(_csv_bytes("utf-8"), today=today)
    row = next(r for r in res.importable if r.amount == 3480)
    prop = build_proposal(row)
    assert len(prop.tax_lines) == 1
    line = prop.tax_lines[0]
    assert line["rate"] == 10
    assert line["base"] + line["tax"] == 3480


# --- Tests del parser: idempotencia ---------------------------------------


def test_dedup_hash_stable() -> None:
    """El hash de dedup es estable e ignora mayusculas/espacios del vendor."""
    h1 = row_dedup_hash(datetime.date(2025, 1, 12), 1280, " セブン ")
    h2 = row_dedup_hash(datetime.date(2025, 1, 12), 1280, "セブン")
    assert h1 == h2


def test_dedup_hash_distinct_by_amount() -> None:
    """Montos distintos producen hashes distintos."""
    a = row_dedup_hash(datetime.date(2025, 1, 12), 1280, "店")
    b = row_dedup_hash(datetime.date(2025, 1, 12), 1300, "店")
    assert a != b


def test_reparse_hashes_identical(today: datetime.date) -> None:
    """Re-parsear el mismo CSV produce exactamente los mismos hashes."""
    h1 = sorted(r.dedup_hash for r in parse_csv(_csv_bytes(), today=today).importable)
    h2 = sorted(r.dedup_hash for r in parse_csv(_csv_bytes(), today=today).importable)
    assert h1 == h2
    assert len(set(h1)) == len(h1)  # todos unicos


# --- Tests de endpoints: preview vs commit --------------------------------


@pytest.fixture
def client(engine: Engine, session: Session) -> TestClient:
    """TestClient con un 年度 sembrado y la sesion del fixture inyectada."""
    seed_accounts(session, commit=False)
    taxpayer = Taxpayer(name="テスト太郎", filing_type=FilingType.AOIRO_65)
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


def _upload(client: TestClient, path: str, data: bytes, **form: str):
    """Helper: POST multipart con el CSV adjunto."""
    files = {"file": ("extracto.csv", data, "text/csv")}
    return client.post(path, files=files, data=form)


def test_preview_returns_rows_and_journal(client: TestClient) -> None:
    """El preview devuelve filas parseadas con su 仕訳 propuesto, sin persistir."""
    resp = _upload(client, "/api/v1/import/csv/preview", _csv_bytes("shift_jis"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["mapping_ok"] is True
    assert body["encoding"] in ("cp932", "shift_jis")
    assert body["total_rows"] == 5
    assert body["importable_count"] == 4
    # Cada fila importable trae 仕訳 propuesto.
    importable = [r for r in body["rows"] if r["importable"]]
    assert all(r["journal_suggestion"] is not None for r in importable)
    assert all(r["account_code"] for r in importable)


def test_preview_does_not_persist(client: TestClient, session: Session) -> None:
    """El preview NO crea transacciones en la BD."""
    _upload(client, "/api/v1/import/csv/preview", _csv_bytes())
    count = session.query(Transaction).count()
    assert count == 0


def test_commit_persists_pending(client: TestClient, session: Session) -> None:
    """El commit persiste las filas como transacciones pending (source=csv)."""
    preview = _upload(
        client, "/api/v1/import/csv/preview", _csv_bytes()
    ).json()
    rows = [
        {
            "dedup_hash": r["dedup_hash"],
            "date": r["date"],
            "vendor": r["vendor"],
            "total_amount": r["total_amount"],
            "account_code": r["account_code"],
            "tax_lines": r["tax_lines"],
        }
        for r in preview["rows"]
        if r["importable"]
    ]
    resp = client.post("/api/v1/import/csv/commit", json={"rows": rows})
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 4
    assert body["skipped_duplicates"] == 0
    # Persistidas como CSV pending.
    txs = session.query(Transaction).all()
    assert len(txs) == 4
    assert all(t.source == TransactionSource.CSV for t in txs)
    assert all(str(t.status) == "pending" for t in txs)


def test_commit_idempotent_no_duplicates(
    client: TestClient, session: Session
) -> None:
    """Re-importar el mismo CSV no duplica: el 2do commit omite todo."""
    preview = _upload(client, "/api/v1/import/csv/preview", _csv_bytes()).json()
    rows = [
        {
            "dedup_hash": r["dedup_hash"],
            "date": r["date"],
            "vendor": r["vendor"],
            "total_amount": r["total_amount"],
            "account_code": r["account_code"],
            "tax_lines": r["tax_lines"],
        }
        for r in preview["rows"]
        if r["importable"]
    ]
    first = client.post("/api/v1/import/csv/commit", json={"rows": rows}).json()
    assert first["imported"] == 4

    # Segundo commit identico: todo duplicado.
    second = client.post("/api/v1/import/csv/commit", json={"rows": rows}).json()
    assert second["imported"] == 0
    assert second["skipped_duplicates"] == 4
    assert session.query(Transaction).count() == 4


def test_preview_flags_duplicates_after_commit(
    client: TestClient, session: Session
) -> None:
    """Tras un commit, el preview del mismo CSV marca las filas como duplicadas."""
    preview = _upload(client, "/api/v1/import/csv/preview", _csv_bytes()).json()
    rows = [
        {
            "dedup_hash": r["dedup_hash"],
            "date": r["date"],
            "vendor": r["vendor"],
            "total_amount": r["total_amount"],
            "account_code": r["account_code"],
            "tax_lines": r["tax_lines"],
        }
        for r in preview["rows"]
        if r["importable"]
    ]
    client.post("/api/v1/import/csv/commit", json={"rows": rows})

    repreview = _upload(client, "/api/v1/import/csv/preview", _csv_bytes()).json()
    assert repreview["duplicate_count"] == 4
    assert repreview["importable_count"] == 0


def test_imported_rows_appear_in_journal_tray(
    client: TestClient, session: Session
) -> None:
    """Las transacciones CSV importadas aparecen en la bandeja de 仕訳."""
    preview = _upload(client, "/api/v1/import/csv/preview", _csv_bytes()).json()
    rows = [
        {
            "dedup_hash": r["dedup_hash"],
            "date": r["date"],
            "vendor": r["vendor"],
            "total_amount": r["total_amount"],
            "account_code": r["account_code"],
            "tax_lines": r["tax_lines"],
        }
        for r in preview["rows"]
        if r["importable"]
    ]
    client.post("/api/v1/import/csv/commit", json={"rows": rows})

    tray = client.get("/api/v1/receipts?status=pending")
    assert tray.status_code == 200
    items = tray.json()
    assert len(items) == 4
    assert all(item["status"] == "pending" for item in items)


def test_preview_empty_file_400(client: TestClient) -> None:
    """Un archivo vacio devuelve 400 con mensaje de dominio."""
    resp = _upload(client, "/api/v1/import/csv/preview", b"")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "empty_file"


def test_preview_with_manual_mapping(client: TestClient) -> None:
    """Un mapping manual (JSON) sobreescribe la auto-deteccion."""
    # CSV con headers que la auto-deteccion no reconoceria por nombre.
    rows = [
        ["A", "B", "C"],
        ["2025/06/01", "謎の店", "2,000"],
    ]
    buf = io.StringIO()
    import csv as _csv

    _csv.writer(buf).writerows(rows)
    data = buf.getvalue().encode("utf-8")
    mapping = '{"date": 0, "vendor": 1, "debit": 2}'
    resp = _upload(
        client, "/api/v1/import/csv/preview", data, mapping=mapping
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mapping_ok"] is True
    assert body["importable_count"] == 1
    assert body["rows"][0]["vendor"] == "謎の店"
    assert body["rows"][0]["total_amount"] == 2000


def test_commit_no_fiscal_year_422(session: Session) -> None:
    """Sin 年度 abierto, el commit devuelve 422."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    resp = client.post(
        "/api/v1/import/csv/commit",
        json={
            "rows": [
                {
                    "dedup_hash": "x",
                    "date": "2025-01-01",
                    "vendor": "店",
                    "total_amount": 1000,
                    "account_code": "599",
                    "tax_lines": [],
                }
            ]
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "no_fiscal_year"


def test_manual_mapping_to_domain() -> None:
    """`ColumnMapping` manual con solo fecha+amount es usable."""
    m = ColumnMapping(date=0, amount=1)
    assert m.is_usable
