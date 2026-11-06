"""Smoke exclusivo de CI sobre una base vacía y datos públicos sintéticos."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import create_db_engine, get_session_factory
from app.models.entities import Taxpayer, Transaction
from app.models.enums import TransactionStatus
from app.seed.dev_seed import seed_demo_data

if os.environ.get("XTX_SYNTHETIC_SMOKE") != "1":
    raise SystemExit("Este comando requiere una base vacía de CI explícitamente aislada.")

engine = create_db_engine(get_settings().database_url)
with get_session_factory(engine)() as db:
    if db.scalar(select(func.count()).select_from(Taxpayer)):
        raise SystemExit("Se conserva la base existente: el smoke requiere una base vacía.")
    seed_demo_data(db)
    for row in db.scalars(select(Transaction)):
        row.status = TransactionStatus.CONFIRMED
    db.commit()


def call(path: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    request = Request(
        "http://127.0.0.1:8200/api/v1" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urlopen(request, timeout=120)
    except HTTPError as exc:
        response = exc
    with response:
        data = response.read()
        if "/xtx" in path:
            assert response.headers["Cache-Control"] == "no-store"
            assert b"1234567890123456" not in data and b"123456789012" not in data
        return response.status, json.loads(data)


status, draft = call("/filing/draft?year=2025", {})
assert status == 200
base = f"/filing/{draft['draft_id']}/xtx"
status, context = call(base + "/context")
assert status == 200 and "my_number" not in context
payload: dict[str, object] = {
    "identity": {"user_id": "1234567890123456", "my_number": "123456789012",
                 "birth_date": "1980-01-01"},
    "details": {
        "payers": [{"kind": "jigyo", "name": "Synthetic Customer",
                    "location": "Synthetic Address", "gross": context["sales_revenue"],
                    "withholding": context["withholding"]}],
        "premiums": [{"category": category, "label": label, "paid": context[key],
                      "outside_year_end_adjustment": context[key]}
                     for category, label, key in (("social", "社会保険料", "social_insurance"),
                                                  ("ideco", "個人型確定拠出年金", "ideco"))],
        "monthly_sales": [context["sales_revenue"], *([0] * 11)],
        "opening_balances": {}, "business_period": ["2025-01-01", "2025-12-31"],
    },
}
status, report = call(base + "/review", payload)
assert status == 200 and report["schema_valid"] is True, report
assert report["ready_for_submission"] is False
assert "official_import_acceptance" in report["missing"]
status, result = call(base, payload)
assert status == 409 and result["detail"]["code"] == "xtx_not_ready"
print("PASS: XSD oficial en Docker, revisión sintética privada y descarga bloqueada.")
