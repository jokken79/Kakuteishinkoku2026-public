"""Tests de los endpoints de recibos y OCR (con FakeOCRProvider, sin deps externas)."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api import receipts as receipts_api
from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base, FiscalYear, Taxpayer
from app.models.enums import TransactionStatus
from app.seed.accounts import seed_accounts
from app.services.ocr.providers.fake import FakeOCRProvider


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    """Cliente de test con BD SQLite en memoria, 年度 sembrado y fake OCR.

    Yields:
        `TestClient` listo, con `get_db` override-ado y proveedores fake.
    """
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)

    # Sembrar cuentas + un Taxpayer + un FiscalYear abierto.
    session: Session = factory()
    seed_accounts(session, commit=False)
    taxpayer = Taxpayer(name="テスト太郎")
    session.add(taxpayer)
    session.flush()
    session.add(
        FiscalYear(taxpayer_id=taxpayer.id, year=2025, rules_ref="tax_rules/2025.json")
    )
    session.commit()
    session.close()

    def _override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    receipts_api.set_test_providers([FakeOCRProvider()])
    # Apuntar el archivado de evidencia a tmp.
    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.evidence_dir = str(tmp_path / "evidence")

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        receipts_api.set_test_providers(None)
        get_settings.cache_clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_manual_expense_requires_review_and_valid_year_and_category(client: TestClient) -> None:
    payload = {
        "year": 2025, "date": "2025-03-15", "vendor": "Taller",
        "total_amount": 70000, "account_code": "599",
    }
    response = client.post("/api/v1/receipts/manual", json=payload)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["status"] == "pending"
    assert item["evidence_id"] is None
    assert any(t["id"] == item["id"] for t in client.get(
        "/api/v1/receipts", params={"year": 2025, "status": "pending"}
    ).json())
    wrong_date = client.post("/api/v1/receipts/manual", json={**payload, "date": "2026-01-01"})
    wrong_category = client.post("/api/v1/receipts/manual", json={**payload, "account_code": "bad"})
    assert wrong_date.status_code == 422
    assert wrong_category.status_code == 422
    assert client.post("/api/v1/receipts/manual", json={**payload, "year": 2026}).status_code == 404


def test_post_receipt_returns_proposal(client: TestClient) -> None:
    """POST /receipts con imagen fake devuelve 200 + estructura completa."""
    response = client.post(
        "/api/v1/receipts",
        files={"file": ("recibo.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["provider_used"] == "fake"
    assert body["confidence_level"] == "high"
    assert body["transaction"]["status"] == TransactionStatus.PENDING.value
    assert body["transaction"]["total_amount"] == 868
    assert body["transaction"]["is_qualified_invoice"] is True

    journal = body["journal_suggestion"]
    debit = sum(ln["amount"] for ln in journal["lines"] if ln["side"] == "debit")
    credit = sum(ln["amount"] for ln in journal["lines"] if ln["side"] == "credit")
    assert debit == credit == 868


def test_post_empty_file_rejected(client: TestClient) -> None:
    """Un archivo vacio devuelve 400."""
    response = client.post(
        "/api/v1/receipts",
        files={"file": ("empty.jpg", b"", "image/jpeg")},
    )
    assert response.status_code == 400


def test_list_pending_and_confirm(client: TestClient) -> None:
    """Flujo: subir -> listar pending -> confirmar -> ya no pending."""
    post = client.post(
        "/api/v1/receipts",
        files={"file": ("r.jpg", b"img", "image/jpeg")},
    )
    tx_id = post.json()["transaction"]["id"]

    pending = client.get("/api/v1/receipts", params={"status": "pending"})
    assert pending.status_code == 200
    assert any(t["id"] == tx_id for t in pending.json())

    confirm = client.post(f"/api/v1/receipts/{tx_id}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"

    pending_after = client.get("/api/v1/receipts", params={"status": "pending"})
    assert all(t["id"] != tx_id for t in pending_after.json())


def test_patch_receipt(client: TestClient) -> None:
    """PATCH edita el vendor de una transaccion."""
    post = client.post(
        "/api/v1/receipts", files={"file": ("r.jpg", b"img", "image/jpeg")}
    )
    tx_id = post.json()["transaction"]["id"]

    patch = client.patch(
        f"/api/v1/receipts/{tx_id}", json={"vendor": "編集済みベンダー"}
    )
    assert patch.status_code == 200
    assert patch.json()["vendor"] == "編集済みベンダー"


def test_post_receipt_includes_account_and_field_confidences(client: TestClient) -> None:
    """POST /receipts devuelve account_code (sugerido) y field_confidences."""
    post = client.post(
        "/api/v1/receipts", files={"file": ("r.jpg", b"img", "image/jpeg")}
    )
    tx = post.json()["transaction"]
    assert tx["account_code"] is not None
    assert isinstance(tx["field_confidences"], dict)
    assert "total" in tx["field_confidences"]


def test_patch_receipt_account_code_persists(client: TestClient) -> None:
    """PATCH del 勘定科目 persiste (se ve al re-listar)."""
    post = client.post(
        "/api/v1/receipts", files={"file": ("r.jpg", b"img", "image/jpeg")}
    )
    tx_id = post.json()["transaction"]["id"]

    patch = client.patch(f"/api/v1/receipts/{tx_id}", json={"account_code": "504"})
    assert patch.status_code == 200
    assert patch.json()["account_code"] == "504"

    listed = client.get("/api/v1/receipts").json()
    edited = next(t for t in listed if t["id"] == tx_id)
    assert edited["account_code"] == "504"


def test_batch_confirm(client: TestClient) -> None:
    """POST /receipts/batch-confirm confirma varias transacciones."""
    ids = []
    # Bytes distintos: la misma imagen se deduplica a proposito (ver los tests
    # de duplicados mas abajo).
    for n in range(2):
        post = client.post(
            "/api/v1/receipts", files={"file": ("r.jpg", f"img-{n}".encode(), "image/jpeg")}
        )
        ids.append(post.json()["transaction"]["id"])
    assert len(set(ids)) == 2

    batch = client.post("/api/v1/receipts/batch-confirm", json={"transaction_ids": ids})
    assert batch.status_code == 200
    assert {t["status"] for t in batch.json()} == {"confirmed"}


def test_list_receipts_filters_by_year(client: TestClient, tmp_path) -> None:
    """GET /receipts filtra por 年度: no mezcla transacciones de años distintos.

    Sube un recibo (cae en el 年度 OPEN 2025 del fixture), abre un 年度 2026 vacío
    y verifica que la bandeja de 2026 NO trae la transacción de 2025, mientras la
    de 2025 sí la trae.
    """
    post = client.post(
        "/api/v1/receipts", files={"file": ("r.jpg", b"img", "image/jpeg")}
    )
    tx_id = post.json()["transaction"]["id"]

    # Abrir un 年度 nuevo (2026), aún sin transacciones.
    created = client.post("/api/v1/fiscal-years", json={"year": 2026})
    assert created.status_code == 200, created.text

    # Sin year => año activo (OPEN más reciente). Ambos 2025 y 2026 están OPEN;
    # 2026 es el más reciente => su bandeja está vacía.
    default_tray = client.get("/api/v1/receipts").json()
    assert all(t["id"] != tx_id for t in default_tray)

    # year=2026 explícito: bandeja vacía (no contiene la tx de 2025).
    tray_2026 = client.get("/api/v1/receipts", params={"year": 2026}).json()
    assert all(t["id"] != tx_id for t in tray_2026)

    # year=2025 explícito: contiene la transacción subida.
    tray_2025 = client.get("/api/v1/receipts", params={"year": 2025}).json()
    assert any(t["id"] == tx_id for t in tray_2025)


def test_upload_receipt_honors_explicit_year(client: TestClient) -> None:
    """El selector puede enviar el año y evita guardar en otro 年度 abierto."""
    client.post("/api/v1/fiscal-years", json={"year": 2026})
    uploaded = client.post(
        "/api/v1/receipts",
        data={"year": "2025"},
        files={"file": ("r.jpg", b"explicit-year", "image/jpeg")},
    )
    assert uploaded.status_code == 200, uploaded.text
    transaction_id = uploaded.json()["transaction"]["id"]
    assert any(
        item["id"] == transaction_id
        for item in client.get("/api/v1/receipts", params={"year": 2025}).json()
    )
    assert all(
        item["id"] != transaction_id
        for item in client.get("/api/v1/receipts", params={"year": 2026}).json()
    )


def test_list_receipts_unknown_year_is_empty(client: TestClient) -> None:
    """GET /receipts con un 年度 inexistente devuelve lista vacía (no error)."""
    client.post("/api/v1/receipts", files={"file": ("r.jpg", b"img", "image/jpeg")})
    res = client.get("/api/v1/receipts", params={"year": 1999})
    assert res.status_code == 200, res.text
    assert res.json() == []


def test_evidence_archive_lists_filters_and_downloads_original(client: TestClient) -> None:
    """El archivo permite buscar por índices y descargar exactamente el original."""
    original = b"evidence-original-bytes"
    uploaded = client.post(
        "/api/v1/receipts",
        files={"file": ("receipt.jpg", original, "image/jpeg")},
    )
    assert uploaded.status_code == 200, uploaded.text
    transaction = uploaded.json()["transaction"]

    listed = client.get("/api/v1/evidence", params={"year": 2025})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total_count"] == 1
    assert body["total_amount"] == 868
    item = body["items"][0]
    assert item["transaction_id"] == transaction["id"]
    assert item["vendor"] == transaction["vendor"]
    assert item["file_available"] is True
    assert item["source"] == "ocr"

    filtered = client.get(
        "/api/v1/evidence",
        params={"year": 2025, "vendor": transaction["vendor"], "amount_min": 800},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total_count"] == 1
    excluded = client.get(
        "/api/v1/evidence", params={"year": 2025, "amount_min": 1_000}
    )
    assert excluded.json()["items"] == []

    downloaded = client.get(f"/api/v1/evidence/{item['id']}/file")
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == original


def test_get_ocr_providers(client: TestClient) -> None:
    """GET /ocr/providers lista los estados de los proveedores."""
    response = client.get("/api/v1/ocr/providers")
    assert response.status_code == 200
    body = response.json()

    assert "allow_external_ocr" in body
    assert body["primary"] == "paddle"
    names = {p["name"] for p in body["providers"]}
    assert {"paddle", "azure", "google", "gemini", "fake"} <= names

    gemini = next(p for p in body["providers"] if p["name"] == "gemini")
    assert gemini["sends_data_externally"] is True
    paddle = next(p for p in body["providers"] if p["name"] == "paddle")
    assert paddle["sends_data_externally"] is False
    # GLM-OCR (Z.AI) es CLOUD: badge ámbar "外部に送信" (no debe verse verde).
    glm = next(p for p in body["providers"] if p["name"] == "glm")
    assert glm["sends_data_externally"] is True
    # OCR local (Ollama): badge verde "端末内" — el dato no sale del equipo.
    ollama = next(p for p in body["providers"] if p["name"] == "ollama")
    assert ollama["sends_data_externally"] is False


def test_patch_ocr_providers_persists(client: TestClient) -> None:
    """PATCH /ocr/providers persiste el switch maestro y los flags por proveedor."""
    patch = client.patch(
        "/api/v1/ocr/providers",
        json={"allow_external_ocr": True, "providers": {"gemini": True}},
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["allow_external_ocr"] is True
    gemini = next(p for p in body["providers"] if p["name"] == "gemini")
    assert gemini["enabled"] is True

    # El GET posterior refleja el override persistido.
    after = client.get("/api/v1/ocr/providers").json()
    assert after["allow_external_ocr"] is True
    assert next(p for p in after["providers"] if p["name"] == "gemini")["enabled"]


def test_patch_ocr_providers_rejects_unknown(client: TestClient) -> None:
    """PATCH /ocr/providers rechaza proveedores no toggleables (ej. 'fake')."""
    patch = client.patch(
        "/api/v1/ocr/providers", json={"providers": {"fake": True}}
    )
    assert patch.status_code == 400


def test_patch_ocr_consent_blocks_cloud(client: TestClient) -> None:
    """Con allow_external_ocr=False, un cloud enabled queda no-usable."""
    client.patch(
        "/api/v1/ocr/providers",
        json={"allow_external_ocr": False, "providers": {"gemini": True}},
    )
    body = client.get("/api/v1/ocr/providers").json()
    gemini = next(p for p in body["providers"] if p["name"] == "gemini")
    assert gemini["enabled"] is True
    assert gemini["usable"] is False


def test_get_ocr_usage_shape(client: TestClient) -> None:
    """GET /ocr/usage devuelve un contador por proveedor cloud."""
    response = client.get("/api/v1/ocr/usage")
    assert response.status_code == 200
    body = response.json()
    names = {u["provider"] for u in body["providers"]}
    assert {"gemini", "glm", "azure", "google"} == names
    gemini = next(u for u in body["providers"] if u["provider"] == "gemini")
    assert set(gemini) >= {
        "used_today", "daily_limit", "percent", "over_limit", "warn", "resets_at"
    }
    assert gemini["daily_limit"] == 200  # default conservador.


def test_patch_daily_limit_persists(client: TestClient) -> None:
    """PATCH /ocr/providers ajusta el limite diario de un proveedor cloud."""
    patch = client.patch(
        "/api/v1/ocr/providers", json={"daily_limits": {"gemini": 75}}
    )
    assert patch.status_code == 200
    usage = client.get("/api/v1/ocr/usage").json()
    gemini = next(u for u in usage["providers"] if u["provider"] == "gemini")
    assert gemini["daily_limit"] == 75


def test_patch_daily_limit_rejects_non_cloud(client: TestClient) -> None:
    """PATCH rechaza ajustar la cuota de un proveedor no-cloud (paddle)."""
    patch = client.patch(
        "/api/v1/ocr/providers", json={"daily_limits": {"paddle": 10}}
    )
    assert patch.status_code == 400


def test_patch_daily_limit_rejects_invalid_value(client: TestClient) -> None:
    """PATCH rechaza un limite diario <= 0."""
    patch = client.patch(
        "/api/v1/ocr/providers", json={"daily_limits": {"gemini": 0}}
    )
    assert patch.status_code == 400


def test_same_photo_twice_does_not_duplicate(client: TestClient) -> None:
    """La misma foto subida dos veces devuelve el mismo 取引, no uno nuevo.

    Es el error tipico sacando fotos en la calle. La segunda subida ni siquiera
    vuelve a llamar al OCR (`provider_used == "cache"`), asi no gasta cuota.
    """
    payload = {"file": ("r.jpg", b"same-photo-bytes", "image/jpeg")}
    first = client.post("/api/v1/receipts", files=payload)
    second = client.post(
        "/api/v1/receipts", files={"file": ("r.jpg", b"same-photo-bytes", "image/jpeg")}
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert second.json()["provider_used"] == "cache"
    assert second.json()["transaction"]["id"] == first.json()["transaction"]["id"]
    assert second.json()["duplicate_of"] == first.json()["transaction"]["id"]
    assert second.json()["journal_suggestion"]["lines"]

    pending = client.get("/api/v1/receipts", params={"status": "pending"}).json()
    assert len(pending) == 1


def test_soft_duplicate_flags_same_purchase(client: TestClient) -> None:
    """Otra foto de la misma compra (fecha+金額+取引先) se marca como sospechosa."""
    client.post("/api/v1/receipts", files={"file": ("a.jpg", b"photo-a", "image/jpeg")})
    second = client.post(
        "/api/v1/receipts", files={"file": ("b.jpg", b"photo-b", "image/jpeg")}
    )

    body = second.json()
    # Bytes distintos: se crea el 取引, pero avisando del posible doble conteo.
    assert body["duplicate"] is False
    assert body["duplicate_of"] is not None
    assert body["duplicate_of"] != body["transaction"]["id"]


def test_confirm_with_corrections_learns_vendor_rule(client: TestClient) -> None:
    """Confirmar corrigiendo el 科目 lo aplica y lo aprende para la proxima foto."""
    first = client.post(
        "/api/v1/receipts", files={"file": ("r1.jpg", b"photo-1", "image/jpeg")}
    ).json()
    proposed = first["journal_suggestion"]["account_code"]
    chosen = "506" if proposed != "506" else "504"

    confirmed = client.post(
        f"/api/v1/receipts/{first['transaction']['id']}/confirm",
        json={"account_code": chosen},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["account_code"] == chosen

    # La siguiente foto del mismo 取引先 ya viene con el 科目 elegido.
    second = client.post(
        "/api/v1/receipts", files={"file": ("r2.jpg", b"photo-2", "image/jpeg")}
    ).json()
    assert second["journal_suggestion"]["account_code"] == chosen
    assert second["account_source"] == "learned"


def test_confirm_without_body_still_works(client: TestClient) -> None:
    """Confirmar sin correcciones sigue siendo un POST sin cuerpo."""
    tx_id = client.post(
        "/api/v1/receipts", files={"file": ("r.jpg", b"photo-plain", "image/jpeg")}
    ).json()["transaction"]["id"]

    response = client.post(f"/api/v1/receipts/{tx_id}/confirm")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"


def test_vendor_rules_are_listed_and_deletable(client: TestClient) -> None:
    """Las reglas aprendidas se pueden ver y borrar (aprendizaje reversible)."""
    tx_id = client.post(
        "/api/v1/receipts", files={"file": ("r.jpg", b"photo-rules", "image/jpeg")}
    ).json()["transaction"]["id"]
    client.post(f"/api/v1/receipts/{tx_id}/confirm", json={"account_code": "505"})

    rules = client.get("/api/v1/receipts/vendor-rules")
    assert rules.status_code == 200, rules.text
    listed = rules.json()
    assert len(listed) == 1
    assert listed[0]["account_code"] == "505"
    assert listed[0]["hits"] == 1

    deleted = client.delete(f"/api/v1/receipts/vendor-rules/{listed[0]['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/receipts/vendor-rules").json() == []
    assert client.delete(f"/api/v1/receipts/vendor-rules/{listed[0]['id']}").status_code == 404
