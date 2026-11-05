"""Datos semilla del dominio fiscal.

Expone la insercion de 勘定科目 estandar de 個人事業主 y el mapeo inicial
vendor -> 科目 usado para auto-clasificar transacciones.
"""

from app.seed.accounts import DEFAULT_ACCOUNTS, seed_accounts
from app.seed.vendor_mapping import (
    VENDOR_ACCOUNT_MAPPING,
    classify_vendor,
    load_vendor_mapping,
)

__all__ = [
    "DEFAULT_ACCOUNTS",
    "VENDOR_ACCOUNT_MAPPING",
    "classify_vendor",
    "load_vendor_mapping",
    "seed_accounts",
]
