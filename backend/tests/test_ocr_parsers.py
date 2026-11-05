"""Tests de los parsers OCR (logica pura): fecha, monto, tasa, 登録番号, vendor."""

from __future__ import annotations

import datetime

import pytest

from app.services.ocr.parsers.amount import parse_amount
from app.services.ocr.parsers.date import parse_date
from app.services.ocr.parsers.reg_number import (
    find_registration_numbers,
    parse_registration_number,
    validate_checksum,
)
from app.services.ocr.parsers.tax_rate import parse_tax_lines
from app.services.ocr.parsers.vendor import parse_vendor

_REF = datetime.date(2026, 1, 1)


# --- Fecha ----------------------------------------------------------------


def test_parse_date_reiwa_kanji() -> None:
    """令和6年5月3日 -> 2024-05-03 (令和N = 2018+N)."""
    assert parse_date("令和6年5月3日", today=_REF) == datetime.date(2024, 5, 3)


def test_parse_date_reiwa_gannen() -> None:
    """令和元年 = 令和1 = 2019."""
    assert parse_date("令和元年12月1日", today=_REF) == datetime.date(2019, 12, 1)


def test_parse_date_reiwa_abbreviated() -> None:
    """R6.5.3 -> 2024-05-03."""
    assert parse_date("R6.5.3", today=_REF) == datetime.date(2024, 5, 3)


def test_parse_date_heisei() -> None:
    """平成30年 = 2018."""
    assert parse_date("平成30年1月1日", today=_REF) == datetime.date(2018, 1, 1)


def test_parse_date_seireki() -> None:
    """Calendario gregoriano directo."""
    assert parse_date("2025/12/31", today=_REF) == datetime.date(2025, 12, 31)
    assert parse_date("2025年7月8日", today=_REF) == datetime.date(2025, 7, 8)


def test_parse_date_rejects_future() -> None:
    """Una fecha futura respecto a `today` se descarta."""
    assert parse_date("令和20年1月1日", today=_REF) is None  # 2038, futuro


def test_parse_date_none_when_absent() -> None:
    """Sin fecha en el texto devuelve None."""
    assert parse_date("ありがとうございました", today=_REF) is None


# --- Monto ----------------------------------------------------------------


def test_parse_amount_total_with_yen_symbol() -> None:
    """合計 ¥1,200 -> 1200."""
    info = parse_amount("商品A 800\n合計 ¥1,200")
    assert info.total == 1200


def test_parse_amount_tax_included() -> None:
    """合計（税込）detecta is_tax_included=True."""
    info = parse_amount("合計（税込） 868円")
    assert info.total == 868
    assert info.is_tax_included is True


def test_parse_amount_tax_excluded() -> None:
    """税抜 marca is_tax_included=False."""
    info = parse_amount("合計（税抜） 1000円")
    assert info.total == 1000
    assert info.is_tax_included is False


def test_parse_amount_fullwidth_digits() -> None:
    """Digitos full-width y comas se normalizan."""
    info = parse_amount("合計 ￥１，２３４円")
    assert info.total == 1234


# --- Tasa (8% / 10% split) ------------------------------------------------


def test_parse_tax_lines_split_8_10() -> None:
    """内8%対象 / 内10%対象 producen dos lineas separadas."""
    text = (
        "内8%対象 348円\n内消費税(8%) 25円\n"
        "内10%対象 520円\n内消費税(10%) 47円\n"
    )
    lines = parse_tax_lines(text)
    by_rate = {line.rate: line for line in lines}
    assert set(by_rate) == {8, 10}
    assert by_rate[8].base == 323 and by_rate[8].tax == 25
    assert by_rate[10].base == 473 and by_rate[10].tax == 47


def test_parse_tax_lines_single_rate() -> None:
    """Una sola tasa -> una sola linea."""
    lines = parse_tax_lines("内10%対象 1100円\n内消費税(10%) 100円")
    assert len(lines) == 1
    assert lines[0].rate == 10


def test_parse_tax_lines_none() -> None:
    """Sin tasas devuelve lista vacia."""
    assert parse_tax_lines("ありがとう") == []


# --- 登録番号 (checksum) ---------------------------------------------------


def test_validate_checksum_roundtrip() -> None:
    """El digito de control generado por el algoritmo valida."""
    assert validate_checksum("9234567890123") is True


def test_validate_checksum_invalid() -> None:
    """Alterar el digito de control invalida el numero."""
    assert validate_checksum("0234567890123") is False


def test_validate_checksum_wrong_length() -> None:
    """Longitud distinta de 13 es invalida."""
    assert validate_checksum("123") is False


def test_parse_registration_number_valid() -> None:
    """登録番号 valido se detecta con checksum True."""
    reg = parse_registration_number("登録番号 T9234567890123")
    assert reg is not None
    assert reg.value == "T9234567890123"
    assert reg.is_valid_checksum is True


def test_parse_registration_number_invalid_checksum() -> None:
    """Numero con checksum invalido se devuelve pero marcado False."""
    reg = parse_registration_number("T0234567890123")
    assert reg is not None
    assert reg.is_valid_checksum is False


def test_parse_registration_number_tolerates_postal_mark() -> None:
    """〒 confundido con T se tolera."""
    reg = parse_registration_number("〒9234567890123")
    assert reg is not None
    assert reg.value == "T9234567890123"


def test_parse_registration_number_tolerates_newline() -> None:
    """Numero partido por espacios/saltos se reconstruye."""
    reg = parse_registration_number("T 9234 5678 90123")
    assert reg is not None
    assert reg.value == "T9234567890123"


def test_find_multiple_registration_numbers() -> None:
    """Multiples numeros se detectan; se prefiere el valido."""
    text = "T0000000000000\nT9234567890123"
    found = find_registration_numbers(text)
    assert len(found) == 2
    best = parse_registration_number(text)
    assert best is not None and best.value == "T9234567890123"


# --- Vendor ---------------------------------------------------------------


def test_parse_vendor_company_hint() -> None:
    """Una linea con 店/株式会社 en el encabezado se toma como vendor."""
    text = "スーパーマルショク 新宿店\n令和6年5月3日\n合計 868円"
    assert parse_vendor(text) == "スーパーマルショク 新宿店"


def test_parse_vendor_skips_noise() -> None:
    """Lineas de metadata (fecha/monto) no se eligen como vendor."""
    text = "Amazon.co.jp\n2025/05/03\n合計 ¥1,200"
    assert parse_vendor(text) == "Amazon.co.jp"


@pytest.mark.parametrize("text", ["", "   \n  "])
def test_parse_vendor_empty(text: str) -> None:
    """Texto vacio devuelve None."""
    assert parse_vendor(text) is None
