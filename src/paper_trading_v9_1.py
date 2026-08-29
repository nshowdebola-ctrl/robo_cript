#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.1
Auditoria do esquema financeiro e conversão segura do CSV legado.

Não inventa taxas/notional históricos.
Gera um schema financeiro pronto para novos trades.
"""
from __future__ import annotations
import argparse, csv, os
from datetime import datetime, timezone

FIN_FIELDS = [
    "trade_id","scenario","symbol","entry_time","exit_time",
    "entry_price","exit_price","quantity","notional",
    "entry_fee","exit_fee","fee_rate",
    "slippage_entry","slippage_exit",
    "gross_pnl","gross_return_pct","net_pnl","net_return_pct",
    "capital_before","capital_after","position_id","exit_reason","holding_hours"
]

LEGACY = {"symbol","entry_time","exit_time","entry_price","exit_price","return_pct"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default="data/paper_trading_v8_trades.csv")
    ap.add_argument("--output",default="data/paper_trading_v9_financial_schema.csv")
    args=ap.parse_args()

    with open(args.input,newline="",encoding="utf-8-sig") as f:
        rows=list(csv.DictReader(f))
    if not rows: raise SystemExit("CSV vazio.")
    missing=LEGACY-set(rows[0])
    if missing: raise SystemExit("CSV não possui campos mínimos: "+", ".join(sorted(missing)))

    with open(args.output,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIN_FIELDS)
        w.writeheader()
        # Deliberately empty financial values: this is a template, not fake history.
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.1 -- SCHEMA FINANCEIRO")
    print("="*100)
    print(f"Trades legados detectados: {len(rows)}")
    print("Campos financeiros históricos: NÃO RECUPERÁVEIS")
    print(f"Schema novo: {args.output}")
    print("Nenhuma taxa, notional, quantity ou P&L financeiro foi inventado.")
    print("A partir de agora, o motor V9 deve preencher esses campos em cada operação.")
    print("="*100)

if __name__=="__main__":
    main()
