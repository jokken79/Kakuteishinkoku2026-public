"""Parser de XML de 控除証明書 electrónicos del NTA -> Deduction candidata.

Pipeline (espejo del de import_csv, pero leyendo XML oficial del e-Tax):

    xml_bytes
      -> ElementTree.fromstring (tolerante a namespace)
      -> detect_type (root element local: TEG800/810/820/821/822/830/840/850)
      -> parse_koujo: extrae montos por XPath del `koujo_schema.json`
      -> KoujoParseResult (DeductionType destino, 控除額, emisor, año, detalles)

Reglas de seguridad (NUNCA inventar montos):
- Los XPaths salen EXCLUSIVAMENTE del `koujo_schema.json` (fuente de verdad de
  los XSD oficiales). Si un campo está ausente en el XML, se degrada (no se
  inventa).
- 生命保険料控除 (TEG800): el XML trae montos pagados por categoría (一般/介護医療/
  個人年金 × 新旧); el 控除額 real sale de la fórmula escalonada oficial del NTA
  (`seimei_hoken_deduction`). Si no se puede calcular con certeza, se marca
  `needs_confirmation=True` y NO se persiste un monto dudoso.
- iDeCo/小規模 (TEG850): `WPI00000` (控除合計額) es directo.
- 地震保険 (TEG810): el 控除対象保険料 (WDE00180) es directo.

NO valida criptográficamente la firma `dsig:Signature` (fuera de alcance del
import básico), pero tampoco la elimina.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from app.models.enums import DeductionType

logger = logging.getLogger(__name__)

# Ruta del esquema (fuente de verdad de XPaths/labels, generado de los XSD NTA).
_SCHEMA_PATH = Path(__file__).with_name("koujo_schema.json")

# Namespace compartido de todos los documentos 控除証明書 (XSD/kyotsu).
_KYOTSU_NS = "http://xml.e-tax.nta.go.jp/XSD/kyotsu"
XmlElement = Any


class KoujoParseError(Exception):
    """Error de parseo de un XML de 控除証明書 (degradación con gracia).

    Args:
        code: Código estable para el cliente (ej. ``unknown_koujo_type``).
        message: Mensaje en japonés listo para mostrar al usuario.
        details: Contexto adicional (opcional).
    """

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass
class SeimeiCategoryDetail:
    """Desglose de una categoría del 生命保険料控除 (一般/介護医療/個人年金).

    Args:
        category: Clave de categoría (``ippan``/``kaigo_iryo``/``nenkin``).
        label: Etiqueta japonesa de la categoría.
        old_paid: Monto pagado bajo 旧制度 (yenes), o ``None``.
        new_paid: Monto pagado bajo 新制度 (yenes), o ``None``.
        deduction: 控除額 calculado para la categoría (yenes).
    """

    category: str
    label: str
    old_paid: int | None
    new_paid: int | None
    deduction: int


@dataclass
class KoujoParseResult:
    """Resultado del parseo de un XML de 控除証明書.

    Args:
        koujo_type: Etiqueta japonesa del tipo de 控除 detectado.
        root_element: Elemento raíz local del XML (ej. ``TEG850``).
        deduction_type: `DeductionType` destino de la Deduction a crear.
        amount: 控除額 a registrar (yenes). Es el monto deducible final salvo
            cuando ``needs_confirmation`` (entonces es el mejor estimado).
        issuer: Emisor / 保険会社名 / 団体名 (puede ser ``None``).
        year: Año 西暦 del certificado (puede ser ``None``).
        needs_confirmation: ``True`` si el 控除額 no es 100% determinable del XML
            y el usuario debe confirmarlo antes de persistir.
        note: Aviso japonés para el preview (ej. por qué requiere confirmación).
        details: Metadatos del parseo (categorías, montos crudos) para meta/debug.
    """

    koujo_type: str
    root_element: str
    deduction_type: DeductionType
    amount: int
    issuer: str | None = None
    year: int | None = None
    needs_confirmation: bool = False
    note: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """Carga (y cachea) el `koujo_schema.json`.

    Returns:
        El esquema completo como dict.
    """
    with _SCHEMA_PATH.open(encoding="utf-8") as fh:
        return cast(dict[str, Any], json.load(fh))


# --- Helpers de XML (tolerantes a namespace) -------------------------------


def _local_name(tag: str) -> str:
    """Devuelve el nombre local de un tag, descartando el namespace.

    Args:
        tag: Tag posiblemente con prefijo ``{ns}local``.

    Returns:
        El nombre local (sin namespace).
    """
    return tag.rsplit("}", 1)[-1]


def _find_local(element: XmlElement, path: list[str]) -> XmlElement | None:
    """Navega por nombres locales (ignora el namespace) siguiendo ``path``.

    El XSD del NTA usa un único namespace para todos los elementos; en vez de
    arrastrar el prefijo en cada XPath, navegamos por nombre local. Esto evita
    hardcodear el namespace y tolera variantes de prefijo del emisor.

    Args:
        element: Elemento de partida.
        path: Secuencia de nombres locales a descender.

    Returns:
        El elemento hijo final, o ``None`` si algún segmento no existe.
    """
    current: XmlElement | None = element
    for segment in path:
        if current is None:
            return None
        nxt: XmlElement | None = None
        for child in current:
            if _local_name(child.tag) == segment:
                nxt = child
                break
        current = nxt
    return current


def _text_at(element: XmlElement, path: list[str]) -> str | None:
    """Texto (stripeado) del elemento en ``path``, o ``None`` si no existe/vacío."""
    node = _find_local(element, path)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _int_at(element: XmlElement, path: list[str]) -> int | None:
    """Entero (gen:kingaku) del elemento en ``path``, o ``None`` si no parsea.

    ``gen:kingaku`` es ``xsd:long`` entero en yenes; se usa ``int()`` directo.

    Args:
        element: Elemento de partida.
        path: Ruta de nombres locales hasta el monto.

    Returns:
        El entero, o ``None`` si el elemento falta o no es numérico.
    """
    text = _text_at(element, path)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        logger.warning("Monto no numérico en %s: %r", "/".join(path), text)
        return None


def _xpath_segments(xpath: str, *, root_local: str) -> list[str]:
    """Convierte un XPath del schema en segmentos locales RELATIVOS al root.

    Los XPaths del schema vienen como ``TEG850/WPG00000/WPG00020`` (con el root)
    o como ``WCE00010`` (relativos a un nodo de detalle). Esta función descarta
    el primer segmento si coincide con el root, devolviendo la ruta a navegar
    desde el elemento raíz.

    Args:
        xpath: XPath tal cual aparece en el schema.
        root_local: Nombre local del root (ej. ``TEG850``).

    Returns:
        Lista de nombres locales relativos al root.
    """
    parts = [p for p in xpath.split("/") if p]
    if parts and parts[0] == root_local:
        parts = parts[1:]
    return parts


def _wareki_to_seireki(era: int, yy: int, schema: dict[str, Any]) -> int | None:
    """Convierte un año 元号 (era + yy) a 西暦 usando la tabla del schema.

    Args:
        era: Código de era (1=明治 … 5=令和).
        yy: Año dentro de la era.
        schema: El esquema cargado (tiene la tabla ``wareki_to_seireki``).

    Returns:
        Año 西暦, o ``None`` si la era no está en la tabla.
    """
    table = schema["import_strategy"]["year_parsing"]["wareki_to_seireki"]
    entry = table.get(str(era))
    if entry is None:
        return None
    return cast(int, entry["offset"] + yy)


def _read_year(element: XmlElement, path: list[str], schema: dict[str, Any]) -> int | None:
    """Lee un año 西暦 desde un elemento gen:yyyy o gen:yy (元号).

    Detecta la forma por los hijos: ``<yyyy>`` (西暦) o ``<era>+<yy>`` (元号).

    Args:
        element: Elemento de partida.
        path: Ruta al nodo del año.
        schema: Esquema cargado (para la tabla wareki).

    Returns:
        Año 西暦, o ``None``.
    """
    node = _find_local(element, path)
    if node is None:
        return None
    yyyy = _text_at(node, ["yyyy"])
    if yyyy is not None:
        try:
            return int(yyyy)
        except ValueError:
            return None
    era = _text_at(node, ["era"])
    yy = _text_at(node, ["yy"])
    if era is not None and yy is not None:
        try:
            return _wareki_to_seireki(int(era), int(yy), schema)
        except ValueError:
            return None
    return None


# --- Fórmula oficial del 生命保険料控除 -------------------------------------


def _new_system_amount(paid: int) -> int:
    """控除額 de una categoría bajo 新制度 (vigente desde 平成24/2012).

    Tabla oficial del NTA (por categoría, sobre el pagado anual):
        ≤ 20,000           -> todo
        20,001 - 40,000    -> pagado÷2 + 10,000
        40,001 - 80,000    -> pagado÷4 + 20,000
        > 80,000           -> 40,000 (tope)

    Args:
        paid: Monto pagado anual de la categoría (yenes).

    Returns:
        控除額 de la categoría bajo 新制度.
    """
    if paid <= 0:
        return 0
    if paid <= 20_000:
        return paid
    if paid <= 40_000:
        return paid // 2 + 10_000
    if paid <= 80_000:
        return paid // 4 + 20_000
    return 40_000


def _old_system_amount(paid: int) -> int:
    """控除額 de una categoría bajo 旧制度 (contratos hasta 平成23/2011).

    Tabla oficial del NTA (por categoría):
        ≤ 25,000           -> todo
        25,001 - 50,000    -> pagado÷2 + 12,500
        50,001 - 100,000   -> pagado÷4 + 25,000
        > 100,000          -> 50,000 (tope)

    Args:
        paid: Monto pagado anual de la categoría (yenes).

    Returns:
        控除額 de la categoría bajo 旧制度.
    """
    if paid <= 0:
        return 0
    if paid <= 25_000:
        return paid
    if paid <= 50_000:
        return paid // 2 + 12_500
    if paid <= 100_000:
        return paid // 4 + 25_000
    return 50_000


def _category_deduction(old_paid: int | None, new_paid: int | None) -> int:
    """控除額 de una categoría que puede tener montos 新 y 旧 (一般/個人年金).

    Regla oficial cuando hay ambos: el mayor entre
        - 旧制度 solo,
        - 新制度 solo,
        - (新制度 + 旧制度), acotado al tope de la categoría (40,000).
    Cada categoría queda topada en 40,000 (cuando interviene 新制度) o 50,000
    (solo 旧制度).

    Args:
        old_paid: Pagado 旧制度 (yenes) o ``None``.
        new_paid: Pagado 新制度 (yenes) o ``None``.

    Returns:
        控除額 de la categoría.
    """
    old_d = _old_system_amount(old_paid or 0)
    new_d = _new_system_amount(new_paid or 0)
    if old_paid and new_paid:
        combined = min(old_d + new_d, 40_000)
        return max(old_d, new_d, combined)
    if new_paid:
        return new_d
    return old_d


# Tope global del 生命保険料控除 (令和7: ¥120,000). Es también `seimei_hoken_max`
# en los tax_rules, pero el parser no depende de TaxRules (capa de import).
_SEIMEI_GLOBAL_CAP = 120_000


# --- Parseo por tipo --------------------------------------------------------


def _field_segments(type_def: dict[str, Any], key: str, root_local: str) -> list[str]:
    """Segmentos locales (relativos al root) del XPath del campo ``key``.

    Atajo sobre `_xpath_segments` para no repetir el acceso al schema en cada
    extracción (mantiene las líneas dentro del límite de ruff).

    Args:
        type_def: Definición del tipo en el schema (``schema["types"][...]``).
        key: Clave del campo dentro de ``fields``.
        root_local: Nombre local del root.

    Returns:
        Lista de nombres locales relativos al root.
    """
    return _xpath_segments(type_def["fields"][key]["xpath"], root_local=root_local)


def _parse_seimei(root: XmlElement, schema: dict[str, Any]) -> KoujoParseResult:
    """Parsea un 生命保険料控除証明書 (TEG800) y calcula el 控除額.

    Recorre las filas de detalle (WCE00000), agrega los 差引保険料 por categoría
    (一般/介護医療/個人年金) y sistema (新/旧), aplica la fórmula escalonada del NTA
    y el tope global. El 介護医療 solo existe en 新制度.

    Args:
        root: Elemento raíz TEG800.
        schema: Esquema cargado.

    Returns:
        `KoujoParseResult` con el 控除額 y el desglose por categoría.
    """
    type_def = schema["types"]["seimei_hoken"]
    root_local = type_def["root_element"]
    issuer = _text_at(root, _field_segments(type_def, "insurance_company_name", root_local))

    # Acumuladores de pagado por categoría/sistema (差引保険料等合計額 = neto).
    ippan_old = 0
    ippan_new = 0
    kaigo_new = 0
    nenkin_old = 0
    nenkin_new = 0
    year: int | None = None

    detail_path = _field_segments(type_def, "detail_rows", root_local)
    detail_container = detail_path[:-1] if len(detail_path) > 1 else []
    detail_local = detail_path[-1] if detail_path else "WCE00000"
    base = _find_local(root, detail_container) if detail_container else root
    rows = (
        [c for c in base if _local_name(c.tag) == detail_local] if base is not None else []
    )

    for row in rows:
        if year is None:
            year = _read_year(row, ["WCE00010"], schema)
        # 旧制度: WCE00220 -> 一般(WCE00230/WCE00260), 年金(WCE00270/WCE00300).
        ippan_old += _int_at(row, ["WCE00190", "WCE00220", "WCE00230", "WCE00260"]) or 0
        nenkin_old += _int_at(row, ["WCE00190", "WCE00220", "WCE00270", "WCE00300"]) or 0
        # 新制度: WCE00310 -> 一般(WCE00320/WCE00350), 介護医療(WCE00360/WCE00390),
        # 年金(WCE00400/WCE00430).
        ippan_new += _int_at(row, ["WCE00190", "WCE00310", "WCE00320", "WCE00350"]) or 0
        kaigo_new += _int_at(row, ["WCE00190", "WCE00310", "WCE00360", "WCE00390"]) or 0
        nenkin_new += _int_at(row, ["WCE00190", "WCE00310", "WCE00400", "WCE00430"]) or 0

    ippan_d = _category_deduction(ippan_old or None, ippan_new or None)
    kaigo_d = _new_system_amount(kaigo_new)
    nenkin_d = _category_deduction(nenkin_old or None, nenkin_new or None)
    total = min(ippan_d + kaigo_d + nenkin_d, _SEIMEI_GLOBAL_CAP)

    categories = [
        SeimeiCategoryDetail(
            "ippan", "一般生命保険", ippan_old or None, ippan_new or None, ippan_d
        ),
        SeimeiCategoryDetail(
            "kaigo_iryo", "介護医療保険", None, kaigo_new or None, kaigo_d
        ),
        SeimeiCategoryDetail(
            "nenkin", "個人年金保険", nenkin_old or None, nenkin_new or None, nenkin_d
        ),
    ]

    any_amount = any(c.old_paid or c.new_paid for c in categories)
    needs_confirmation = not any_amount
    note: str | None = None
    if needs_confirmation:
        note = (
            "証明書から保険料の金額を読み取れませんでした。"
            "控除証明書を見て、控除額をご確認ください。"
        )
    else:
        note = (
            "保険料から控除額を自動計算しました（一般・介護医療・個人年金の合計）。"
            "金額をご確認のうえ登録してください。"
        )

    return KoujoParseResult(
        koujo_type=type_def["label"],
        root_element=root_local,
        deduction_type=DeductionType.SEIMEI_HOKEN,
        amount=total,
        issuer=issuer,
        year=year,
        needs_confirmation=needs_confirmation,
        note=note,
        details={
            "categories": [
                {
                    "category": c.category,
                    "label": c.label,
                    "old_paid": c.old_paid,
                    "new_paid": c.new_paid,
                    "deduction": c.deduction,
                }
                for c in categories
            ],
            "global_cap": _SEIMEI_GLOBAL_CAP,
        },
    )


def _parse_jishin(root: XmlElement, schema: dict[str, Any]) -> KoujoParseResult:
    """Parsea un 地震保険料控除証明書 (TEG810): 控除対象保険料 directo.

    Suma el 控除対象保険料 (WDE00180) de cada fila de detalle. El 旧長期損害保険
    (WDE00210) también aporta a la misma deducción (tope conjunto ¥50,000 lo
    aplica el cálculo fiscal; aquí se suman los montos certificados).

    Args:
        root: Elemento raíz TEG810.
        schema: Esquema cargado.

    Returns:
        `KoujoParseResult` con el monto deducible del 地震保険料控除.
    """
    type_def = schema["types"]["jishin_hoken"]
    root_local = type_def["root_element"]
    issuer = _text_at(root, _field_segments(type_def, "insurance_company_name", root_local))

    detail_path = _field_segments(type_def, "detail_rows", root_local)
    detail_local = detail_path[-1] if detail_path else "WDE00000"
    rows = [c for c in root if _local_name(c.tag) == detail_local]

    earthquake_total = 0
    old_longterm_total = 0
    year: int | None = None
    for row in rows:
        if year is None:
            year = _read_year(row, ["WDE00010"], schema)
        earthquake_total += _int_at(row, ["WDE00160", "WDE00180"]) or 0
        old_longterm_total += _int_at(row, ["WDE00190", "WDE00210"]) or 0

    amount = earthquake_total + old_longterm_total
    needs_confirmation = amount <= 0
    note = (
        "証明書から控除対象保険料を読み取れませんでした。金額をご確認ください。"
        if needs_confirmation
        else "地震保険料控除の対象額を読み取りました。"
    )

    return KoujoParseResult(
        koujo_type=type_def["label"],
        root_element=root_local,
        deduction_type=DeductionType.JISHIN_HOKEN,
        amount=amount,
        issuer=issuer,
        year=year,
        needs_confirmation=needs_confirmation,
        note=note,
        details={
            "earthquake": earthquake_total,
            "old_longterm": old_longterm_total,
        },
    )


def _parse_shoukibo_ideco(root: XmlElement, schema: dict[str, Any]) -> KoujoParseResult:
    """Parsea un 小規模企業共済等掛金控除証明書 (TEG850): 控除合計額 directo.

    Usa ``WPI00000`` (控除合計額) como monto deducible. Si falta, cae al
    払込済額 (WPG00020) como mejor estimado y marca confirmación.

    Args:
        root: Elemento raíz TEG850.
        schema: Esquema cargado.

    Returns:
        `KoujoParseResult` con el monto deducible del iDeCo/小規模.
    """
    type_def = schema["types"]["shoukibo_kyosai_ideco"]
    root_local = type_def["root_element"]
    subscriber = _text_at(root, _field_segments(type_def, "subscriber_name", root_local))
    year = _read_year(root, _field_segments(type_def, "certificate_year", root_local), schema)

    total = _int_at(root, _field_segments(type_def, "total_deductible_amount", root_local))
    paid = _int_at(root, _field_segments(type_def, "paid_amount", root_local))
    scheduled = _int_at(root, _field_segments(type_def, "scheduled_amount", root_local))

    if total is not None and total > 0:
        amount = total
        needs_confirmation = False
        note = "控除合計額をそのまま読み取りました。"
    elif paid is not None:
        amount = paid + (scheduled or 0)
        needs_confirmation = True
        note = (
            "控除合計額が見つからなかったため、払込済額（＋予定額）を表示しています。"
            "金額をご確認ください。"
        )
    else:
        amount = 0
        needs_confirmation = True
        note = "証明書から掛金額を読み取れませんでした。金額をご確認ください。"

    return KoujoParseResult(
        koujo_type=type_def["label"],
        root_element=root_local,
        deduction_type=DeductionType.IDECO,
        amount=amount,
        issuer=subscriber,
        year=year,
        needs_confirmation=needs_confirmation,
        note=note,
        details={"total": total, "paid": paid, "scheduled": scheduled},
    )


def _parse_kokumin_nenkin(root: XmlElement, schema: dict[str, Any]) -> KoujoParseResult:
    """Parsea un 国民年金保険料等控除証明書 (TEG840): aporta a 社会保険料控除.

    El 国民年金 es 社会保険料控除 (全額対象, sin tope). Usa ``WOM00000`` (合計額)
    o, si falta, ``WOK00000`` (納付済額) + ``WOL00000`` (見込額).

    Args:
        root: Elemento raíz TEG840.
        schema: Esquema cargado.

    Returns:
        `KoujoParseResult` con el monto deducible del 社会保険料控除.
    """
    type_def = schema["types"]["kokumin_nenkin"]
    root_local = type_def["root_element"]
    insured = _text_at(root, _field_segments(type_def, "insured_name", root_local))
    year = _read_year(root, _field_segments(type_def, "certificate_year_1", root_local), schema)

    total = _int_at(root, _field_segments(type_def, "total_amount", root_local))
    paid = _int_at(root, _field_segments(type_def, "paid_amount", root_local))
    estimated = _int_at(root, _field_segments(type_def, "estimated_amount", root_local))

    if total is not None and total > 0:
        amount = total
        needs_confirmation = False
        note = "国民年金の合計額を読み取りました（社会保険料控除に加算されます）。"
    elif paid is not None:
        amount = paid + (estimated or 0)
        needs_confirmation = True
        note = (
            "合計額が見つからなかったため、納付済額（＋見込額）を表示しています。"
            "金額をご確認ください。"
        )
    else:
        amount = 0
        needs_confirmation = True
        note = "証明書から納付額を読み取れませんでした。金額をご確認ください。"

    return KoujoParseResult(
        koujo_type=type_def["label"],
        root_element=root_local,
        deduction_type=DeductionType.SHAKAI_HOKEN,
        amount=amount,
        issuer=insured,
        year=year,
        needs_confirmation=needs_confirmation,
        note=note,
        details={"total": total, "paid": paid, "estimated": estimated},
    )


# Tipos de 寄附金 (受領証明書 単体/複数/R3 + 寄附金控除証明書): todos -> FURUSATO.
def _parse_kifu(root: XmlElement, schema: dict[str, Any], schema_key: str) -> KoujoParseResult:
    """Parsea un certificado de 寄附金 (TEG820/821/822/830): suma de donaciones.

    Suma los montos de donación de las filas de detalle. El 控除額 fiscal
    (donación − ¥2,000, tope 40% 総所得) lo calcula el motor fiscal; aquí se
    persiste el total donado (que es lo que el wizard de ふるさと納税 espera como
    `amount`).

    Args:
        root: Elemento raíz del certificado.
        schema: Esquema cargado.
        schema_key: Clave del tipo en el schema (``furusato_nozei_single`` etc.).

    Returns:
        `KoujoParseResult` con el total donado (FURUSATO).
    """
    type_def = schema["types"][schema_key]
    root_local = type_def["root_element"]

    # TEG830 (寄附金控除証明書) trae el total anual directo (WMF00000); el resto
    # son 受領証明書 con filas de detalle.
    if schema_key == "kifu_kojo_shomei":
        page1 = _find_local(root, ["TEG830-1"])
        total = _int_at(page1, ["WMF00000"]) if page1 is not None else None
        issuer = _text_at(page1, ["WMJ00000"]) if page1 is not None else None
        year = _read_year(page1, ["WMA00000"], schema) if page1 is not None else None
        amount = total or 0
    else:
        detail_field = type_def["fields"]["detail_rows"]
        detail_path = _xpath_segments(detail_field["xpath"], root_local=root_local)
        detail_local = detail_path[-1] if detail_path else ""
        amount_local = detail_field["children"]["donation_amount"]["xpath"].split("/")[-1]
        rows = [c for c in root if _local_name(c.tag) == detail_local]
        amount = sum(_int_at(row, [amount_local]) or 0 for row in rows)
        issuer = None
        year = None
        # Nombre del donante / organización si está en el nivel raíz.
        for cand in ("donor_name", "organization_name"):
            field_def = type_def["fields"].get(cand)
            if field_def is not None:
                issuer = _text_at(root, _xpath_segments(field_def["xpath"], root_local=root_local))
                if issuer:
                    break

    needs_confirmation = amount <= 0
    note = (
        "証明書から寄附金額を読み取れませんでした。金額をご確認ください。"
        if needs_confirmation
        else (
            "寄附金額を読み取りました。確定申告ではワンストップ特例は無効になり、"
            "今年の寄附はすべて申告が必要です。"
        )
    )

    return KoujoParseResult(
        koujo_type=type_def["label"],
        root_element=root_local,
        deduction_type=DeductionType.FURUSATO,
        amount=amount,
        issuer=issuer,
        year=year,
        needs_confirmation=needs_confirmation,
        note=note,
        details={"donation_total": amount},
    )


# Mapa root element local -> (clave del schema, parser).
_ROOT_DISPATCH: dict[str, str] = {
    "TEG800": "seimei",
    "TEG810": "jishin",
    "TEG820": "kifu:furusato_nozei_single",
    "TEG821": "kifu:furusato_nozei_multi",
    "TEG822": "kifu:furusato_nozei_multi_r3",
    "TEG830": "kifu:kifu_kojo_shomei",
    "TEG840": "kokumin_nenkin",
    "TEG850": "shoukibo_ideco",
}


def detect_type(root: XmlElement) -> str:
    """Detecta el tipo de 控除証明書 por el nombre local del elemento raíz.

    Args:
        root: Elemento raíz del XML.

    Returns:
        El nombre local del root (ej. ``TEG850``).

    Raises:
        KoujoParseError: Si el root no es un tipo soportado.
    """
    local = _local_name(root.tag)
    if local not in _ROOT_DISPATCH:
        raise KoujoParseError(
            code="unknown_koujo_type",
            message=(
                "対応していない控除証明書です。"
                "生命保険・地震保険・iDeCo（小規模企業共済）・国民年金・寄附金の"
                "XML証明書に対応しています。"
            ),
            details={"root_element": local},
        )
    return local


def parse_koujo_xml(data: bytes) -> KoujoParseResult:
    """Parsea los bytes de un XML de 控除証明書 a una Deduction candidata.

    Detecta el tipo por el elemento raíz y delega al parser específico. NO
    persiste nada ni valida la firma criptográficamente.

    Args:
        data: Bytes crudos del archivo XML.

    Returns:
        `KoujoParseResult` con el tipo, el 控除額 y los detalles.

    Raises:
        KoujoParseError: Si el XML está vacío, malformado o es de un tipo no
            soportado.
    """
    if not data or not data.strip():
        raise KoujoParseError(
            code="empty_file",
            message="XMLファイルが空です。",
        )
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise KoujoParseError(
            code="invalid_xml",
            message="XMLとして読み取れませんでした。ファイル形式をご確認ください。",
            details={"error": str(exc)},
        ) from exc

    schema = load_schema()
    local = detect_type(root)
    dispatch = _ROOT_DISPATCH[local]

    if dispatch == "seimei":
        return _parse_seimei(root, schema)
    if dispatch == "jishin":
        return _parse_jishin(root, schema)
    if dispatch == "shoukibo_ideco":
        return _parse_shoukibo_ideco(root, schema)
    if dispatch == "kokumin_nenkin":
        return _parse_kokumin_nenkin(root, schema)
    if dispatch.startswith("kifu:"):
        return _parse_kifu(root, schema, dispatch.split(":", 1)[1])

    # Inalcanzable (detect_type ya filtró), pero degrada con gracia.
    raise KoujoParseError(
        code="unknown_koujo_type",
        message="対応していない控除証明書です。",
        details={"root_element": local},
    )
