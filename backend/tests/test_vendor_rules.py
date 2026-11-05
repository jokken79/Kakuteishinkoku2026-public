"""Tests de la memoria 取引先 -> 勘定科目 (`app.services.vendor_rules`)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.vendor_rules import (
    LearnedAccountClassifier,
    learn_rule,
    lookup_rule,
    normalize_vendor,
)


def test_normalize_vendor_unifica_ancho_espacios_y_sufijos() -> None:
    """全角/半角, espacios y 株式会社 no deben partir la misma tienda en dos reglas."""
    assert normalize_vendor("ＦＡＭＩＬＹ ＭＡＲＴ") == normalize_vendor("family mart")
    assert normalize_vendor("株式会社ヤマダ電機") == normalize_vendor("ヤマダ電機")
    assert normalize_vendor("セブン-イレブン") == "セブンイレブン"
    assert normalize_vendor(None) == ""
    assert normalize_vendor("   ") == ""


def test_learn_rule_crea_y_refuerza(session: Session) -> None:
    """Confirmar dos veces el mismo 科目 refuerza la regla en vez de duplicarla."""
    first = learn_rule(session, "スターバックス 渋谷店", "504")
    assert first is not None
    assert first.hits == 1

    second = learn_rule(session, "スターバックス 渋谷店", "504")
    assert second is not None
    assert second.id == first.id
    assert second.hits == 2


def test_learn_rule_reapunta_al_corregir(session: Session) -> None:
    """Si el usuario cambia el 科目, la regla se reapunta y vuelve a contar."""
    learn_rule(session, "アマゾン", "502")
    learn_rule(session, "アマゾン", "502")
    updated = learn_rule(session, "アマゾン", "506")

    assert updated is not None
    assert updated.account_code == "506"
    assert updated.hits == 1


def test_learn_rule_ignora_datos_incompletos(session: Session) -> None:
    """Sin 取引先 o sin 科目 no hay nada que aprender."""
    assert learn_rule(session, None, "502") is None
    assert learn_rule(session, "ローソン", None) is None


def test_lookup_rule_matchea_sucursales(session: Session) -> None:
    """La regla del 取引先 aplica tambien a sus sucursales (`...渋谷店`)."""
    learn_rule(session, "セブンイレブン", "502")

    hit = lookup_rule(session, "セブン-イレブン 渋谷店")
    assert hit is not None
    assert hit.account_code == "502"
    assert lookup_rule(session, "まったく別の店") is None


def test_lookup_rule_prefiere_la_regla_mas_especifica(session: Session) -> None:
    """Con dos reglas aplicables gana la de clave mas larga (mas especifica)."""
    learn_rule(session, "ヤマダ", "502")
    learn_rule(session, "ヤマダ電機新宿", "506")

    hit = lookup_rule(session, "ヤマダ電機新宿西口店")
    assert hit is not None
    assert hit.account_code == "506"


def test_classifier_antepone_lo_aprendido_al_seed(session: Session) -> None:
    """El 科目 aprendido gana sobre el mapeo semilla y se marca como `learned`."""
    plain = LearnedAccountClassifier(session).suggest("ローソン")
    learn_rule(session, "ローソン", "504")
    learned = LearnedAccountClassifier(session).suggest("ローソン 品川店")

    assert learned.account_code == "504"
    assert learned.source == "learned"
    assert learned.confidence > plain.confidence


def test_classifier_cae_al_seed_sin_regla(session: Session) -> None:
    """Sin regla aprendida, el clasificador sigue usando el mapeo del seed."""
    suggestion = LearnedAccountClassifier(session).suggest("知らない店")
    assert suggestion.source in {"rule", "default"}
