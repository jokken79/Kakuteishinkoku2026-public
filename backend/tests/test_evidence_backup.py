"""Tests del respaldo verificable del archivo de recibos (電帳法).

Lo que se protege: que el respaldo lleve los indices que exige la ley, que
detecte los comprobantes cuyo archivo ya no esta en disco, y sobre todo que la
verificacion **falle** cuando el respaldo se rompe — un backup que siempre dice
"ok" no sirve de nada.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import Evidence, FiscalYear, Taxpayer, Transaction
from app.models.enums import TransactionSource, TransactionStatus
from app.services.evidence_backup import (
    MANIFEST_NAME,
    build_evidence_backup,
    verify_evidence_backup,
)


def _seed_receipt(
    db: Session,
    evidence_dir: Path,
    *,
    payload: bytes,
    vendor: str,
    amount: int,
    day: int,
    write_file: bool = True,
) -> Evidence:
    """Siembra un recibo archivado (Evidence + Transaction).

    Args:
        db: Sesion de BD.
        evidence_dir: Carpeta del almacen de evidencia.
        payload: Bytes del comprobante.
        vendor: 取引先 indexado.
        amount: 金額 indexado.
        day: Dia del 2025-05 para el indice 日付.
        write_file: Si ``False``, registra el comprobante sin escribir el archivo
            (simula una perdida de datos previa).

    Returns:
        El `Evidence` persistido.
    """
    taxpayer = db.query(Taxpayer).first()
    if taxpayer is None:
        taxpayer = Taxpayer(name="テスト太郎")
        db.add(taxpayer)
        db.flush()
    fiscal_year = db.query(FiscalYear).first()
    if fiscal_year is None:
        fiscal_year = FiscalYear(
            taxpayer_id=taxpayer.id, year=2025, rules_ref="tax_rules/2025.json"
        )
        db.add(fiscal_year)
        db.flush()

    digest = hashlib.sha256(payload).hexdigest()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / f"{digest}.bin"
    if write_file:
        target.write_bytes(payload)

    date = _dt.date(2025, 5, day)
    evidence = Evidence(
        file_ref=str(target),
        hash=digest,
        timestamp=_dt.datetime.now(_dt.UTC),
        idx_date=date,
        idx_amount=amount,
        idx_vendor=vendor,
        retention_until=_dt.date(2032, 5, 1),
    )
    db.add(evidence)
    db.flush()
    db.add(
        Transaction(
            fiscal_year_id=fiscal_year.id,
            date=date,
            vendor=vendor,
            total_amount=amount,
            source=TransactionSource.OCR,
            evidence_id=evidence.id,
            status=TransactionStatus.CONFIRMED,
        )
    )
    db.commit()
    return evidence


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings apuntando el almacen de evidencia a `tmp_path`."""
    return Settings(evidence_dir=str(tmp_path / "evidence"))


def test_backup_incluye_los_indices_del_denchoho(
    session: Session, settings: Settings, tmp_path: Path
) -> None:
    """El manifiesto trae 日付/金額/取引先 y el plazo de conservacion."""
    _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-uno",
        vendor="セブンイレブン",
        amount=868,
        day=3,
    )
    out = tmp_path / "backup.zip"

    result = build_evidence_backup(session, settings=settings, out_path=out)

    assert result.archived == 1
    assert result.is_complete
    with zipfile.ZipFile(out) as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    entry = manifest["entries"][0]
    assert entry["idx_vendor"] == "セブンイレブン"
    assert entry["idx_amount"] == 868
    assert entry["idx_date"] == "2025-05-03"
    assert entry["retention_until"] == "2032-05-01"
    assert entry["fiscal_year"] == 2025


def test_backup_reporta_los_archivos_perdidos(
    session: Session, settings: Settings, tmp_path: Path
) -> None:
    """Un comprobante registrado sin archivo en disco se reporta, no se ignora."""
    _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-ok",
        vendor="ローソン",
        amount=500,
        day=4,
    )
    perdido = _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-perdido",
        vendor="ファミマ",
        amount=300,
        day=5,
        write_file=False,
    )
    out = tmp_path / "backup.zip"

    result = build_evidence_backup(session, settings=settings, out_path=out)

    assert result.archived == 1
    assert result.missing == [perdido.hash]
    assert not result.is_complete


def test_backup_filtra_por_anio(
    session: Session, settings: Settings, tmp_path: Path
) -> None:
    """Con `year` explicito solo entra el 年度 pedido."""
    _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-2025",
        vendor="ローソン",
        amount=500,
        day=6,
    )

    assert (
        build_evidence_backup(
            session, settings=settings, out_path=tmp_path / "a.zip", year=2025
        ).archived
        == 1
    )
    assert (
        build_evidence_backup(
            session, settings=settings, out_path=tmp_path / "b.zip", year=2099
        ).archived
        == 0
    )


def test_verify_acepta_un_respaldo_sano(
    session: Session, settings: Settings, tmp_path: Path
) -> None:
    """Un respaldo recien hecho verifica limpio."""
    _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-sano",
        vendor="スーパー",
        amount=1200,
        day=7,
    )
    out = tmp_path / "backup.zip"
    build_evidence_backup(session, settings=settings, out_path=out)

    result = verify_evidence_backup(out)

    assert result.is_valid
    assert result.checked == 1


def test_verify_detecta_contenido_alterado(
    session: Session, settings: Settings, tmp_path: Path
) -> None:
    """Si el contenido cambia, la verificacion lo canta (razon de ser del hash)."""
    _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-original",
        vendor="スーパー",
        amount=1200,
        day=8,
    )
    out = tmp_path / "backup.zip"
    build_evidence_backup(session, settings=settings, out_path=out)

    # Reescribir el ZIP con el comprobante adulterado.
    with zipfile.ZipFile(out) as archive:
        items = {name: archive.read(name) for name in archive.namelist()}
    target = next(name for name in items if name.startswith("evidence/"))
    items[target] = b"contenido-adulterado"
    with zipfile.ZipFile(out, mode="w") as archive:
        for name, data in items.items():
            archive.writestr(name, data)

    result = verify_evidence_backup(out)

    assert not result.is_valid
    assert result.corrupt == [target]


def test_verify_detecta_comprobante_faltante(
    session: Session, settings: Settings, tmp_path: Path
) -> None:
    """Si falta un comprobante que el manifiesto declara, la verificacion falla."""
    _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-a-borrar",
        vendor="スーパー",
        amount=900,
        day=9,
    )
    out = tmp_path / "backup.zip"
    build_evidence_backup(session, settings=settings, out_path=out)

    with zipfile.ZipFile(out) as archive:
        items = {name: archive.read(name) for name in archive.namelist()}
    target = next(name for name in items if name.startswith("evidence/"))
    del items[target]
    with zipfile.ZipFile(out, mode="w") as archive:
        for name, data in items.items():
            archive.writestr(name, data)

    result = verify_evidence_backup(out)

    assert not result.is_valid
    assert result.missing == [target]


def test_verify_rechaza_un_zip_sin_manifiesto(tmp_path: Path) -> None:
    """Sin manifiesto no hay nada contra que verificar."""
    out = tmp_path / "vacio.zip"
    with zipfile.ZipFile(out, mode="w") as archive:
        archive.writestr("evidence/x.bin", b"suelto")

    with pytest.raises(ValueError, match=MANIFEST_NAME):
        verify_evidence_backup(out)


def test_verify_rechaza_un_archivo_inexistente(tmp_path: Path) -> None:
    """Verificar algo que no existe es un error explicito, no un `ok`."""
    with pytest.raises(FileNotFoundError):
        verify_evidence_backup(tmp_path / "no-existe.zip")


def test_cli_verify_devuelve_codigos_de_salida(
    session: Session, settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """El comando sale 0 con un respaldo sano y != 0 si esta roto (para cron)."""
    from app.cli.evidence import main

    _seed_receipt(
        session,
        Path(settings.evidence_dir),
        payload=b"recibo-cli",
        vendor="スーパー",
        amount=700,
        day=10,
    )
    out = tmp_path / "backup.zip"
    build_evidence_backup(session, settings=settings, out_path=out)

    assert main(["verify", str(out)]) == 0

    # Respaldo adulterado -> el comando tiene que fallar, no avisar en silencio.
    with zipfile.ZipFile(out) as archive:
        items = {name: archive.read(name) for name in archive.namelist()}
    target = next(name for name in items if name.startswith("evidence/"))
    items[target] = b"otra-cosa"
    with zipfile.ZipFile(out, mode="w") as archive:
        for name, data in items.items():
            archive.writestr(name, data)

    assert main(["verify", str(out)]) == 1
    assert main(["verify", str(tmp_path / "no-existe.zip")]) == 2
    capsys.readouterr()
