"""Integración REST del módulo 売上・請求."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import create_db_engine, get_db, get_session_factory
from app.main import app
from app.models import Base, FiscalYear, Taxpayer


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine: Engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = get_session_factory(engine)
    db: Session = factory()
    taxpayer = Taxpayer(
        name="形山 健二",
        postal_code="496-0000",
        address="愛知県津島市",
    )
    db.add(taxpayer)
    db.flush()
    db.add(FiscalYear(taxpayer_id=taxpayer.id, year=2025, rules_ref="2025"))
    db.commit()
    db.close()

    def _override_get_db() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _document_payload(document_type: str = "invoice") -> dict[str, object]:
    return {
        "document_type": document_type,
        "customer": {"name": "株式会社青空", "honorific": "御中"},
        "subject": "システム保守業務",
        "issue_date": "2025-11-30",
        "due_date": "2025-12-31",
        "notes": "お振込手数料はご負担ください。",
        "lines": [
            {
                "description": "月次保守サービス",
                "quantity": "1",
                "unit": "式",
                "unit_price": 10_000,
                "tax_category": "standard_10",
            },
            {
                "description": "軽減税率対象品",
                "quantity": "1",
                "unit": "個",
                "unit_price": 1_000,
                "tax_category": "reduced_8",
            },
        ],
    }


def test_business_profile_defaults_and_optional_representative(client: TestClient) -> None:
    response = client.get("/api/v1/business-profile")
    assert response.status_code == 200
    assert response.json()["trade_name"] == "事業者"
    assert response.json()["show_representative"] is False
    assert response.json()["is_invoice_issuer"] is False
    assert response.json()["default_customer_honorific"] == "御中"
    assert response.json()["payment_terms_days"] == 30
    assert response.json()["show_stamp_box"] is True
    assert response.json()["show_logo"] is False
    assert response.json()["logo_ref"] is None
    assert response.json()["show_seal"] is True

    updated = client.patch(
        "/api/v1/business-profile",
        json={
            "show_representative": True,
            "representative_name": "形山 健二",
            "legal_name": "形山 健二",
            "legal_name_kana": "カタヤマ ケンジ",
            "business_description": "システム保守",
            "department_name": "管理部",
            "contact_person_name": "形山",
            "address_line1": "愛知県津島市本町1-2-3",
            "address_line2": "ケイビル2F",
            "fax": "0567-00-0001",
            "website_url": "https://example.jp",
            "default_customer_honorific": "様",
            "payment_terms_days": 14,
            "show_stamp_box": False,
            "show_seal": True,
            "seal_text": "済",
            "invoice_message": "毎度ありがとうございます。",
            "receipt_message": "上記金額を正に領収いたしました。",
            "receipt_proviso": "システム保守費",
            "document_footer_note": "電子発行書類として保管してください。",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["representative_name"] == "形山 健二"
    assert updated.json()["payment_terms_days"] == 14
    assert updated.json()["default_customer_honorific"] == "様"
    assert updated.json()["seal_text"] == "済"

    invalid_corporate = client.patch(
        "/api/v1/business-profile",
        json={"corporate_number": "123"},
    )
    assert invalid_corporate.status_code == 422
    assert invalid_corporate.json()["detail"]["code"] == "invalid_corporate_number"


def test_invoice_issuer_requires_valid_registration_number(client: TestClient) -> None:
    missing = client.patch("/api/v1/business-profile", json={"is_invoice_issuer": True})
    assert missing.status_code == 422
    invalid = client.patch(
        "/api/v1/business-profile",
        json={"is_invoice_issuer": True, "registration_number": "T123"},
    )
    assert invalid.status_code == 422
    valid = client.patch(
        "/api/v1/business-profile",
        json={"is_invoice_issuer": True, "registration_number": "T1234567890123"},
    )
    assert valid.status_code == 200


def test_direct_invoice_issue_pdf_and_immutability(client: TestClient) -> None:
    created = client.post("/api/v1/sales-documents", json=_document_payload())
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["status"] == "draft"
    assert data["subtotal"] == 11_000
    assert data["tax_10"] == 1_000
    assert data["tax_8"] == 80
    assert data["total"] == 12_080

    issued = client.post(f"/api/v1/sales-documents/{data['id']}/issue")
    assert issued.status_code == 200, issued.text
    issued_data = issued.json()
    assert issued_data["status"] == "awaiting_payment"
    assert issued_data["document_number"] == "INV-2025-0001"

    issued_again = client.post(f"/api/v1/sales-documents/{data['id']}/issue")
    assert issued_again.json()["document_number"] == "INV-2025-0001"
    pdf = client.get(f"/api/v1/sales-documents/{data['id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 2_000

    locked = client.patch(
        f"/api/v1/sales-documents/{data['id']}",
        json={"subject": "変更不可"},
    )
    assert locked.status_code == 409


def test_estimate_conversion_and_direct_receipt(client: TestClient) -> None:
    estimate = client.post(
        "/api/v1/sales-documents", json=_document_payload("estimate")
    ).json()
    converted = client.post(
        f"/api/v1/sales-documents/{estimate['id']}/convert",
        json={"target_type": "invoice", "creation_key": "estimate-to-invoice-1"},
    )
    assert converted.status_code == 200, converted.text
    assert converted.json()["source_document_id"] == estimate["id"]
    assert converted.json()["total"] == estimate["total"]

    converted_again = client.post(
        f"/api/v1/sales-documents/{estimate['id']}/convert",
        json={"target_type": "invoice", "creation_key": "estimate-to-invoice-1"},
    )
    assert converted_again.json()["id"] == converted.json()["id"]

    receipt = client.post(
        "/api/v1/sales-documents", json=_document_payload("receipt")
    ).json()
    issued = client.post(f"/api/v1/sales-documents/{receipt['id']}/issue")
    assert issued.status_code == 200
    assert issued.json()["status"] == "paid"
    assert issued.json()["amount_paid"] == issued.json()["total"]


def test_partial_payment_creates_idempotent_receipt(client: TestClient) -> None:
    document = client.post("/api/v1/sales-documents", json=_document_payload()).json()
    client.post(f"/api/v1/sales-documents/{document['id']}/issue")
    payment_payload = {
        "payment_date": "2025-12-15",
        "amount": 5_000,
        "method": "bank_transfer",
        "reference": "BANK-001",
        "idempotency_key": "payment-001",
        "create_receipt": True,
    }
    paid = client.post(
        f"/api/v1/sales-documents/{document['id']}/payments",
        json=payment_payload,
    )
    assert paid.status_code == 201, paid.text
    receipt_id = paid.json()["receipt_document_id"]
    assert receipt_id

    repeated = client.post(
        f"/api/v1/sales-documents/{document['id']}/payments",
        json=payment_payload,
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == paid.json()["id"]

    refreshed = client.get(f"/api/v1/sales-documents/{document['id']}").json()
    assert refreshed["status"] == "partially_paid"
    assert refreshed["amount_paid"] == 5_000
    assert len(refreshed["payments"]) == 1
    receipt_pdf = client.get(f"/api/v1/sales-documents/{receipt_id}/pdf")
    assert receipt_pdf.content.startswith(b"%PDF")


def test_qualified_invoice_blocked_until_settings_enabled(client: TestClient) -> None:
    payload = _document_payload()
    payload["is_qualified_invoice"] = True
    document = client.post("/api/v1/sales-documents", json=payload).json()
    blocked = client.post(f"/api/v1/sales-documents/{document['id']}/issue")
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "invoice_profile_required"


def test_qualified_receipt_uses_professional_pdf_profile(client: TestClient) -> None:
    import fitz

    settings = client.patch(
        "/api/v1/business-profile",
        json={
            "is_invoice_issuer": True,
            "registration_number": "T1234567890123",
            "trade_name": "事業者",
            "show_representative": True,
            "representative_name": "形山 健二",
            "address_line1": "愛知県津島市本町1-2-3",
            "phone": "0567-00-0000",
            "receipt_proviso": "システム保守費",
            "receipt_message": "上記金額を正に領収いたしました。",
            "show_stamp_box": True,
            "show_seal": True,
            "seal_text": "領収",
        },
    )
    assert settings.status_code == 200, settings.text
    assert settings.json()["show_logo"] is False
    assert settings.json()["logo_ref"] is None

    payload = _document_payload("receipt")
    payload["is_qualified_invoice"] = True
    payload["subject"] = "システム保守費"
    created = client.post("/api/v1/sales-documents", json=payload).json()
    issued = client.post(f"/api/v1/sales-documents/{created['id']}/issue")
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "paid"
    assert issued.json()["document_number"].startswith("REC-")

    pdf = client.get(f"/api/v1/sales-documents/{created['id']}/pdf")
    assert pdf.status_code == 200
    assert len(pdf.content) > 3_000
    pdf_doc = fitz.open(stream=pdf.content, filetype="pdf")
    text = "\n".join(page.get_text() for page in pdf_doc)
    assert not any(page.get_images(full=True) for page in pdf_doc)
    assert "領収金額" in text
    assert "収入印紙" in text
    assert "登録番号 T1234567890123" in text


@pytest.mark.parametrize(
    ("document_type", "expected_status"),
    [
        ("estimate", "issued"),
        ("delivery_note", "issued"),
        ("invoice", "awaiting_payment"),
        ("receipt", "paid"),
        ("purchase_order", "issued"),
        ("order_acknowledgement", "issued"),
        ("consolidated_invoice", "awaiting_payment"),
        ("corrected_invoice", "awaiting_payment"),
    ],
)
def test_every_supported_document_type_can_issue_a_pdf(
    client: TestClient,
    document_type: str,
    expected_status: str,
) -> None:
    import fitz

    created = client.post(
        "/api/v1/sales-documents",
        json=_document_payload(document_type),
    )
    assert created.status_code == 201, created.text

    document_id = created.json()["id"]
    issued = client.post(f"/api/v1/sales-documents/{document_id}/issue")
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == expected_status
    assert issued.json()["document_number"]

    pdf = client.get(f"/api/v1/sales-documents/{document_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    pdf_doc = fitz.open(stream=pdf.content, filetype="pdf")
    assert not any(page.get_images(full=True) for page in pdf_doc)
