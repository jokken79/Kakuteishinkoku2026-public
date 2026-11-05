"""Respaldo verificable del archivo de recibos (電子帳簿保存法).

Las imagenes de los recibos son la prueba documental de los gastos y hay que
conservarlas **7 años**. Hasta ahora vivian como archivos sueltos en
`evidence_dir`, sin respaldo ni forma de detectar que uno se perdio o se
corrompio: un disco que falla se lleva la evidencia de toda la declaracion.

Este modulo arma un ZIP con:

- ``00_manifest.json`` — una entrada por comprobante con su SHA-256 y los
  indices que exige el 電帳法 (日付 / 金額 / 取引先), mas el 取引 y el 年度 a los
  que pertenece y hasta cuando hay que conservarlo.
- ``evidence/<hash>.bin`` — el original, tal cual se archivo.

Y sabe **verificarlo**: re-hashea cada archivo del ZIP contra el manifiesto, asi
un respaldo silenciosamente roto se detecta antes de necesitarlo. Un backup que
no se puede verificar no es un backup.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import Evidence, FiscalYear, Transaction

logger = logging.getLogger(__name__)

MANIFEST_NAME = "00_manifest.json"
EVIDENCE_PREFIX = "evidence/"
MANIFEST_VERSION = 1


@dataclass
class BackupResult:
    """Resultado de armar un respaldo.

    Args:
        archive: Ruta del ZIP generado.
        archived: Comprobantes efectivamente incluidos.
        total_bytes: Suma de los tamaños de los originales incluidos.
        missing: Hashes de comprobantes que la BD registra pero cuyo archivo ya
            no esta en disco (perdida de datos **anterior** al respaldo).
    """

    archive: Path
    archived: int
    total_bytes: int
    missing: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """``True`` si no falto ningun archivo en disco."""
        return not self.missing


@dataclass
class VerifyResult:
    """Resultado de verificar un respaldo.

    Args:
        checked: Entradas del manifiesto verificadas.
        missing: Entradas del manifiesto que no estan en el ZIP.
        corrupt: Entradas cuyo contenido no coincide con el hash del manifiesto.
        extra: Archivos del ZIP que no figuran en el manifiesto.
    """

    checked: int
    missing: list[str] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """``True`` si el respaldo esta integro y completo."""
        return not (self.missing or self.corrupt or self.extra)


def _entry_path(digest: str) -> str:
    """Ruta dentro del ZIP para un comprobante.

    Args:
        digest: SHA-256 del original.

    Returns:
        Ruta relativa dentro del archivo.
    """
    return f"{EVIDENCE_PREFIX}{digest}.bin"


def _evidence_file(evidence: Evidence, base: Path) -> Path | None:
    """Resuelve el archivo de un comprobante dentro del almacen configurado.

    Nunca sale de `base`: el `file_ref` guardado no se usa como ruta libre.

    Args:
        evidence: Comprobante archivado.
        base: Carpeta raiz del almacen de evidencia (resuelta).

    Returns:
        Ruta al archivo, o ``None`` si no existe o cae fuera del almacen.
    """
    candidate = Path(evidence.file_ref).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return None
    return candidate


def build_evidence_backup(
    db: Session,
    *,
    settings: Settings,
    out_path: Path,
    year: int | None = None,
) -> BackupResult:
    """Arma el ZIP de respaldo del archivo de recibos.

    Args:
        db: Sesion de BD.
        settings: Settings (carpeta de evidencia).
        out_path: Ruta del ZIP a generar (se crean las carpetas padre).
        year: 年度 a respaldar, o ``None`` para todos.

    Returns:
        `BackupResult` con el conteo y los archivos que faltaban en disco.
    """
    base = Path(settings.evidence_dir).resolve()
    stmt = (
        select(Evidence, Transaction, FiscalYear)
        .join(Transaction, Transaction.evidence_id == Evidence.id)
        .join(FiscalYear, Transaction.fiscal_year_id == FiscalYear.id)
        .order_by(Evidence.idx_date, Evidence.timestamp)
    )
    if year is not None:
        stmt = stmt.where(FiscalYear.year == year)

    entries: list[dict[str, object]] = []
    missing: list[str] = []
    total_bytes = 0
    seen: set[str] = set()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for evidence, transaction, fiscal_year in db.execute(stmt).all():
            path = _evidence_file(evidence, base)
            if path is None:
                missing.append(evidence.hash)
                logger.warning(
                    "Comprobante sin archivo en disco: hash=%s vendor=%r",
                    evidence.hash,
                    evidence.idx_vendor,
                )
                continue

            payload = path.read_bytes()
            # El hash del manifiesto se recalcula del contenido real, no se
            # copia de la BD: si el archivo en disco cambio, se respalda lo que
            # hay y la verificacion despues cuadra contra eso.
            digest = hashlib.sha256(payload).hexdigest()
            if digest not in seen:
                archive.writestr(_entry_path(digest), payload)
                seen.add(digest)
                total_bytes += len(payload)

            entries.append(
                {
                    "hash": digest,
                    "stored_as": _entry_path(digest),
                    "size": len(payload),
                    "db_hash": evidence.hash,
                    "idx_date": evidence.idx_date.isoformat() if evidence.idx_date else None,
                    "idx_amount": evidence.idx_amount,
                    "idx_vendor": evidence.idx_vendor,
                    "archived_at": evidence.timestamp.isoformat(),
                    "retention_until": (
                        evidence.retention_until.isoformat()
                        if evidence.retention_until
                        else None
                    ),
                    "transaction_id": str(transaction.id),
                    "fiscal_year": fiscal_year.year,
                    "source": str(transaction.source),
                    "status": str(transaction.status),
                }
            )

        manifest = {
            "version": MANIFEST_VERSION,
            "generated_at": _dt.datetime.now(_dt.UTC).isoformat(),
            "fiscal_year": year,
            "total_entries": len(entries),
            "total_bytes": total_bytes,
            "missing_on_disk": missing,
            "entries": entries,
        }
        archive.writestr(
            MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2)
        )

    return BackupResult(
        archive=out_path,
        archived=len(entries),
        total_bytes=total_bytes,
        missing=missing,
    )


def verify_evidence_backup(archive_path: Path) -> VerifyResult:
    """Verifica un respaldo re-hasheando su contenido contra el manifiesto.

    Args:
        archive_path: Ruta del ZIP a verificar.

    Returns:
        `VerifyResult` con faltantes, corruptos y sobrantes.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        ValueError: Si el ZIP no trae manifiesto o esta ilegible.
    """
    if not archive_path.is_file():
        raise FileNotFoundError(f"No existe el respaldo: {archive_path}")

    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            if MANIFEST_NAME not in names:
                raise ValueError(f"El respaldo no trae {MANIFEST_NAME}.")
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))

            expected: dict[str, str] = {}
            for entry in manifest.get("entries", []):
                expected[str(entry["stored_as"])] = str(entry["hash"])

            missing: list[str] = []
            corrupt: list[str] = []
            for stored_as, digest in expected.items():
                if stored_as not in names:
                    missing.append(stored_as)
                    continue
                actual = hashlib.sha256(archive.read(stored_as)).hexdigest()
                if actual != digest:
                    corrupt.append(stored_as)

            extra = sorted(
                name
                for name in names
                if name.startswith(EVIDENCE_PREFIX) and name not in expected
            )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"El respaldo esta corrupto o no es un ZIP: {exc}") from exc

    return VerifyResult(
        checked=len(expected),
        missing=sorted(missing),
        corrupt=sorted(corrupt),
        extra=extra,
    )
