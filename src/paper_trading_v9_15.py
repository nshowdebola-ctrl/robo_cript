#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.15
Integração do scanner com o ledger financeiro V9.

Objetivo:
- Ler sinais forward de data/forward_signals.csv.
- Validar o contrato mínimo do sinal.
- Não usar o CSV legado V8 para inventar dados financeiros.
- Registrar entradas no ledger V9 através do motor V9.9/V9.10.
- PAPER ONLY: nenhuma ordem real.

Esta versão funciona como adapter seguro. Ela NÃO cria trades
automaticamente quando não há sinais válidos.
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

SIGNALS = DATA / "forward_signals.csv"
LEDGER = DATA / "paper_trading_v9_financial_trades.csv"

SIGNAL_REQUIRED = {
    "symbol",
    "entry_time",
    "entry_price",
    "scenario",
}

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def parse_dt(value: str) -> datetime:
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    x = datetime.fromisoformat(s)
    if x.tzinfo is None:
        x = x.replace(tzinfo=timezone.utc)
    return x.astimezone(timezone.utc)

def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def validate_signals(rows: List[Dict[str, str]]) -> tuple[List[Dict[str, str]], List[str]]:
    valid = []
    errors = []

    for idx, row in enumerate(rows, 2):
        missing = sorted(k for k in SIGNAL_REQUIRED if not str(row.get(k, "")).strip())
        if missing:
            errors.append(f"linha {idx}: campos ausentes: {', '.join(missing)}")
            continue

        try:
            parse_dt(row["entry_time"])
            price = float(row["entry_price"])
            if price <= 0:
                raise ValueError("entry_price <= 0")
        except Exception as exc:
            errors.append(f"linha {idx}: sinal inválido: {exc}")
            continue

        row = dict(row)
        row["symbol"] = row["symbol"].strip().upper()
        row["scenario"] = row["scenario"].strip()
        valid.append(row)

    return valid, errors

def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.15 -- SCANNER → LEDGER V9")
    print("=" * 100)
    print(f"Sinais: {SIGNALS}")
    print(f"Ledger: {LEDGER}")
    print("Modo: PAPER ONLY")
    print("Ordens reais: NÃO")
    print("CSV legado V8: NÃO UTILIZADO")
    print("-" * 100)

    rows = read_csv(SIGNALS)

    if not rows:
        print("Sinais forward encontrados: 0")
        print("Nenhum sinal foi inventado.")
        print("O adapter está pronto aguardando o scanner.")
        print("=" * 100)
        return 0

    valid, errors = validate_signals(rows)

    print(f"Sinais lidos:        {len(rows)}")
    print(f"Sinais válidos:      {len(valid)}")
    print(f"Sinais rejeitados:   {len(errors)}")

    if errors:
        print("\nERROS DE CONTRATO:")
        for e in errors[:20]:
            print(f"  - {e}")
        if len(errors) > 20:
            print(f"  ... mais {len(errors) - 20} erros")

    print("\nIMPORTANTE:")
    print("V9.15 valida e prepara os sinais; não transforma sinais")
    print("em trades financeiros sem que o motor V9.9/V9.10 execute")
    print("open_trade() com os parâmetros financeiros explícitos.")

    print("\nPróxima integração:")
    print("  scanner -> forward_signals.csv -> V9.15 -> open_trade()")
    print("  -> monitoramento -> close_trade() -> ledger financeiro V9")
    print("=" * 100)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
