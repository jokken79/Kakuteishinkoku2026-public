from fastapi.testclient import TestClient

from app.main import app


def test_preview_preserves_receipt_and_balances_lines() -> None:
    response = TestClient(app).post(
        "/api/v1/mixed-expenses/preview",
        json={
            "original_total": 301,
            "numerator": 1,
            "denominator": 3,
            "lines": [{"gross": 101, "tax_rate": 10}, {"gross": 200, "tax_rate": 8}],
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["original_total"] == 301
    assert result["business_total"] == 100
    assert result["personal_total"] == 201
    assert sum(line["business"] for line in result["lines"]) == 100
    assert result["lines"][0]["original"] == {"gross": 101, "tax_rate": 10}


def test_preview_rejects_nonmatching_lines_and_boolean_amounts() -> None:
    client = TestClient(app)
    payload = {"original_total": 100, "numerator": 1, "denominator": 2, "lines": [{"gross": 99}]}
    assert client.post("/api/v1/mixed-expenses/preview", json=payload).status_code == 422
    payload["original_total"] = True
    assert client.post("/api/v1/mixed-expenses/preview", json=payload).status_code == 422
