#!/usr/bin/env python3
"""Crypto Radar V9.12 - adapter financeiro para sinais forward.

Não lê o CSV legado V8 para inventar dados financeiros.
Recebe um sinal já produzido pelo scanner e abre/fecha operações
através do ledger financeiro V9.
"""
import argparse, csv, os, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from paper_trading_v9_9 import open_trade, close_trade, LEDGER, FIELDS

def parse_dt(s):
    if not s:
        return datetime.now(timezone.utc).isoformat()
    x = s.replace("Z", "+00:00")
    d = datetime.fromisoformat(x)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()

def process_signal(row, notional, fee, slip):
    symbol = row["symbol"].strip().upper()
    entry = float(row["entry_price"])
    exit_price = float(row["exit_price"])
    scenario = row.get("scenario") or "V9_FORWARD"
    entry_time = parse_dt(row.get("entry_time"))
    exit_time = parse_dt(row.get("exit_time"))
    reason = row.get("exit_reason") or "SIGNAL"
    p = open_trade(symbol, entry, notional, scenario=scenario,
                   entry_fee_rate=fee, slippage_entry_pct=slip,
                   entry_time=entry_time)
    return close_trade(p, exit_price, exit_fee_rate=fee,
                       slippage_exit_pct=slip,
                       exit_time=exit_time, exit_reason=reason)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", help="CSV de sinais fechados; não usa V8.")
    ap.add_argument("--notional", type=float, default=100.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slippage", type=float, default=0.1)
    args = ap.parse_args()

    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.12 -- ADAPTER DO SCANNER")
    print("=" * 100)
    print(f"Ledger V9: {LEDGER}")
    print("Modo: PAPER ONLY")
    print("CSV legado V8: NÃO utilizado")
    print(f"Notional: ${args.notional:.2f} | Fee/lado: {args.fee*100:.3f}% | Slippage/lado: {args.slippage:.3f}%")

    if not args.signals:
        print("Nenhum arquivo de sinais fornecido.")
        print("Uso: python3 src/paper_trading_v9_12.py --signals data/forward_signals.csv")
        return 0

    required = {"symbol","entry_price","exit_price"}
    with open(args.signals, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("CSV de sinais vazio.")
        return 0
    missing = required - set(rows[0])
    if missing:
        raise SystemExit("Campos ausentes: " + ", ".join(sorted(missing)))

    before = 0
    try:
        with open(LEDGER, newline="", encoding="utf-8") as f:
            before = sum(1 for _ in f) - 1
    except FileNotFoundError:
        pass

    created = 0
    for row in rows:
        process_signal(row, args.notional, args.fee, args.slippage)
        created += 1

    print(f"Operações financeiras V9 gravadas: {created}")
    print(f"Trades no ledger antes: {max(before,0)}")
    print("Nenhuma operação é criada sem sinal explícito.")
    print("=" * 100)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
