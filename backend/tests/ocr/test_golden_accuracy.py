"""Harness de accuracy field-level sobre el golden set (research §4).

Corre el pipeline OCR sobre un conjunto de recibos sinteticos con ground truth
(`tests/fixtures/ocr/golden/<caso>/{raw.txt, expected.json}`) y compara **campo a
campo** (no CER agregado): 日付 / 金額 / 取引先 / 内訳(税率) / 登録番号. Imprime una
tabla con el % de exact-match por campo y cuantos casos pasan la validacion
aritmetica.

Por que sinteticos: sin API keys reales no se puede medir un provider cloud. Pero
este harness ya queda **listo** para medir cualquier provider real: basta cambiar
la cadena de `FakeOCRProvider` por el provider con key. Hoy mide el techo de los
**parsers de dominio** (que es lo que valida de forma cruzada al LLM): el LLM
propone, esto verifica. La tabla se imprime con ``pytest -s``.

El test es deterministico y no hace llamadas externas (usa `FakeOCRProvider`
parametrizado con el ``raw.txt`` de cada caso).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.ocr.pipeline import process_receipt
from app.services.ocr.providers.fake import FakeOCRProvider

# Fecha de referencia fija (futuro de todos los recibos del golden) para que las
# validaciones de "fecha no futura" sean estables.
_REF = datetime.date(2026, 6, 1)

_GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "ocr" / "golden"

# Campos que se miden a nivel exact-match (etiqueta ASCII-safe para la tabla:
# la consola Windows por defecto es cp932 y no imprime kanji ni em-dash).
_FIELDS = (
    ("date", "date/hizuke"),
    ("total", "total/kingaku"),
    ("vendor", "vendor/torihiki"),
    ("tax_lines", "tax/uchiwake"),
    ("registration_number", "reg/touroku"),
)


@dataclass
class GoldenCase:
    """Un caso del golden set (raw + ground truth).

    Args:
        name: Nombre del directorio del caso.
        raw_text: Texto crudo que devolvera el `FakeOCRProvider`.
        expected: Ground truth (date/vendor/total/tax_lines/registration_number).
    """

    name: str
    raw_text: str
    expected: dict


def _load_golden_cases() -> list[GoldenCase]:
    """Carga todos los casos del golden set desde disco.

    Returns:
        Lista de `GoldenCase` ordenada por nombre. Vacia si no hay fixtures.
    """
    cases: list[GoldenCase] = []
    if not _GOLDEN_DIR.exists():
        return cases
    for case_dir in sorted(_GOLDEN_DIR.iterdir()):
        raw_file = case_dir / "raw.txt"
        exp_file = case_dir / "expected.json"
        if not (raw_file.exists() and exp_file.exists()):
            continue
        cases.append(
            GoldenCase(
                name=case_dir.name,
                raw_text=raw_file.read_text(encoding="utf-8"),
                expected=json.loads(exp_file.read_text(encoding="utf-8")),
            )
        )
    return cases


_CASES = _load_golden_cases()


def _normalize_tax_lines(tax_lines: list[dict]) -> list[dict]:
    """Normaliza tax_lines a ``[{rate, base, tax}]`` para comparar exact-match."""
    return [
        {"rate": tl.get("rate"), "base": tl.get("base"), "tax": tl.get("tax")}
        for tl in tax_lines
    ]


def _field_matches(field: str, got, expected) -> bool:
    """``True`` si el campo extraido coincide exacto con el ground truth.

    Args:
        field: Nombre del campo.
        got: Valor extraido por el pipeline.
        expected: Valor del ground truth.

    Returns:
        ``True`` si coinciden (con la normalizacion correspondiente).
    """
    if field == "date":
        got_iso = got.isoformat() if isinstance(got, datetime.date) else got
        return got_iso == expected
    if field == "tax_lines":
        return _normalize_tax_lines(got) == expected
    return got == expected


def test_golden_set_present() -> None:
    """El golden set tiene al menos 8 casos (cobertura minima del research §4)."""
    assert len(_CASES) >= 8, (
        f"Golden set insuficiente: {len(_CASES)} casos en {_GOLDEN_DIR}."
    )


def test_golden_accuracy_field_level(capsys: pytest.CaptureFixture[str]) -> None:
    """Mide accuracy field-level del pipeline sobre el golden set e imprime tabla.

    Compara cada campo extraido vs el ground truth y reporta el % de exact-match
    por campo + cuantos casos cuadran aritmeticamente. Se imprime con ``-s``.
    """
    settings = Settings(ocr_preprocess_enabled=False)  # raw_text directo, sin imagen.

    field_hits: dict[str, int] = {f: 0 for f, _ in _FIELDS}
    arithmetic_pass = 0
    rows: list[str] = []

    for case in _CASES:
        result = process_receipt(
            b"golden",
            providers=[FakeOCRProvider(text=case.raw_text)],
            today=_REF,
            settings=settings,
        )
        parsed = result.parsed
        per_case: list[str] = []
        for field, _label in _FIELDS:
            got = getattr(parsed, field)
            expected = case.expected.get(field)
            ok = _field_matches(field, got, expected)
            field_hits[field] += 1 if ok else 0
            per_case.append("OK" if ok else "XX")
        if result.validation.arithmetic_ok:
            arithmetic_pass += 1
        rows.append(
            f"  {case.name:26} "
            + " ".join(
                f"{lbl}:{mark}"
                for (_, lbl), mark in zip(_FIELDS, per_case, strict=True)
            )
            + f"  arith:{'OK' if result.validation.arithmetic_ok else 'XX'}"
        )

    n = len(_CASES)
    lines = [
        "",
        "=" * 78,
        f"OCR GOLDEN ACCURACY - field-level ({n} casos sinteticos, FakeOCRProvider)",
        "=" * 78,
        "Por caso:",
        *rows,
        "-" * 78,
        "Exact-match por campo:",
    ]
    for field, label in _FIELDS:
        pct = 100.0 * field_hits[field] / n if n else 0.0
        lines.append(f"  {label:16} {field:22} {field_hits[field]:2}/{n}  {pct:5.1f}%")
    lines.append("-" * 78)
    arith_pct = 100.0 * arithmetic_pass / n if n else 0.0
    lines.append(
        f"  Cuadre aritmetico (base+tax==total): {arithmetic_pass}/{n}  {arith_pct:5.1f}%"
    )
    lines.append("=" * 78)
    lines.append(
        "Nota: mide el techo de los parsers de dominio (validacion cruzada del LLM). "
        "Sin API keys no se mide un provider real; el harness ya queda listo para "
        "medirlo cambiando la cadena por el provider con key."
    )
    lines.append("=" * 78)

    # Imprimir fuera de captura para que se vea con `pytest -s`. Forzar ASCII-safe
    # para no romper en consolas Windows cp932 (los nombres de caso son ASCII).
    report = "\n".join(lines)
    with capsys.disabled():
        print(report.encode("ascii", "replace").decode("ascii"))

    # Umbrales del research §4 (sobre el golden sintetico, parsers de dominio):
    # 日付 y 金額 deben ser perfectos; 登録番号 perfecto (incluye checksum).
    assert field_hits["date"] == n, "日付 deberia ser 100% en el golden."
    assert field_hits["total"] == n, "金額 deberia ser 100% en el golden."
    assert field_hits["registration_number"] == n, "登録番号 deberia ser 100%."
    assert field_hits["tax_lines"] == n, "内訳(税率) deberia ser 100% en el golden."
