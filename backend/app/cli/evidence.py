"""Comando de respaldo y verificacion del archivo de recibos (電帳法).

Uso:

    python -m app.cli.evidence backup --out data/backups/evidencia-2025.zip
    python -m app.cli.evidence backup --year 2025 --out respaldo.zip
    python -m app.cli.evidence verify respaldo.zip

Devuelve codigo de salida != 0 si el respaldo salio incompleto (faltaban
archivos en disco) o si la verificacion encuentra faltantes/corruptos, para que
sirva en una tarea programada sin que nadie lea la salida.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.session import create_db_engine, get_session_factory
from app.services.evidence_backup import (
    build_evidence_backup,
    verify_evidence_backup,
)


def _human(size: int) -> str:
    """Formatea bytes de forma legible.

    Args:
        size: Cantidad de bytes.

    Returns:
        Texto como ``"12.3 MB"``.
    """
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _run_backup(args: argparse.Namespace) -> int:
    """Arma el respaldo y reporta el resultado.

    Args:
        args: Argumentos parseados (``out``, ``year``).

    Returns:
        Codigo de salida (0 = respaldo completo).
    """
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    factory = get_session_factory(engine)
    db = factory()
    try:
        result = build_evidence_backup(
            db, settings=settings, out_path=Path(args.out), year=args.year
        )
    finally:
        db.close()
        engine.dispose()

    print(f"Respaldo: {result.archive}")
    print(f"Comprobantes: {result.archived} ({_human(result.total_bytes)})")
    if result.missing:
        print(
            f"ATENCION: {len(result.missing)} comprobante(s) registrados en la BD "
            "no tienen archivo en disco y NO se pudieron respaldar:",
            file=sys.stderr,
        )
        for digest in result.missing:
            print(f"  - {digest}", file=sys.stderr)
        return 1
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    """Verifica un respaldo existente.

    Args:
        args: Argumentos parseados (``archive``).

    Returns:
        Codigo de salida (0 = respaldo integro).
    """
    try:
        result = verify_evidence_backup(Path(args.archive))
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Verificados: {result.checked} comprobante(s)")
    if result.is_valid:
        print("Respaldo integro.")
        return 0

    for label, items in (
        ("Faltan en el respaldo", result.missing),
        ("Contenido alterado", result.corrupt),
        ("Sobran (sin manifiesto)", result.extra),
    ):
        if items:
            print(f"{label}: {len(items)}", file=sys.stderr)
            for name in items:
                print(f"  - {name}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Arma el parser de argumentos del comando.

    Returns:
        Parser configurado con los subcomandos ``backup`` y ``verify``.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.evidence",
        description="Respaldo verificable del archivo de recibos (電帳法, 7 años).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="Arma el ZIP de respaldo.")
    backup.add_argument("--out", required=True, help="Ruta del ZIP a generar.")
    backup.add_argument(
        "--year", type=int, default=None, help="年度 a respaldar (default: todos)."
    )
    backup.set_defaults(func=_run_backup)

    verify = sub.add_parser("verify", help="Verifica un respaldo existente.")
    verify.add_argument("archive", help="Ruta del ZIP a verificar.")
    verify.set_defaults(func=_run_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del comando.

    Args:
        argv: Argumentos (default: `sys.argv`).

    Returns:
        Codigo de salida del subcomando.
    """
    args = build_parser().parse_args(argv)
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
