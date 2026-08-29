#!/usr/bin/env python3
import csv, os
from datetime import datetime, timezone

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(BASE, "data")
LEDGER = os.path.join(DATA, "paper_trading_v9_financial_trades.csv")

FIELDS = [
    "trade_id","scenario","symbol","entry_time","exit_time",
    "entry_price","exit_price","quantity","notional",
    "entry_fee_rate","exit_fee_rate","entry_fee","exit_fee",
    "slippage_entry_pct","slippage_exit_pct",
    "gross_return_pct","net_return_pct","gross_pnl","net_pnl",
    "exit_reason","holding_hours"
]

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def main():
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(LEDGER):
        with open(LEDGER, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()
        created = True
    else:
        created = False

    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.3 -- LEDGER FINANCEIRO FORWARD")
    print("=" * 100)
    print(f"Arquivo: {LEDGER}")
    print("Objetivo: registrar NOVAS operações com dados financeiros explícitos.")
    print("CSV legado V8: NÃO utilizado para inventar fees/notional.")
    print("Ordens reais: NÃO")
    print("-" * 100)
    print("Schema:", ", ".join(FIELDS))
    print("Criado agora:" if created else "Já existente:", LEDGER)
    print()
    print("O ledger está pronto para receber operações financeiras V9.")
    print("Próxima etapa: o motor V9 deve gravar cada operação fechada neste arquivo.")
    print("=" * 100)

if __name__ == "__main__":
    main()
