#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.19
Auditoria do ciclo forward e integridade do ledger.

Não cria, fecha ou modifica trades.
Não usa o CSV legado V8.
"""

from pathlib import Path
import csv
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OPEN_FILE = DATA / "paper_trading_v9_open_positions.csv"
LEDGER_FILE = DATA / "paper_trading_v9_financial_trades.csv"

LEDGER_FIELDS = [
    "trade_id", "scenario", "symbol", "entry_time", "exit_time",
    "entry_price", "exit_price", "quantity", "notional",
    "entry_fee_rate", "exit_fee_rate", "entry_fee", "exit_fee",
    "slippage_entry_pct", "slippage_exit_pct",
    "gross_return_pct", "net_return_pct",
    "gross_pnl", "net_pnl", "exit_reason", "holding_hours"
]

NUMERIC_FIELDS = [
    "entry_price", "exit_price", "quantity", "notional",
    "entry_fee_rate", "exit_fee_rate", "entry_fee", "exit_fee",
    "slippage_entry_pct", "slippage_exit_pct",
    "gross_return_pct", "net_return_pct", "gross_pnl",
    "net_pnl", "holding_hours"
]

def load(path):
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames or [], list(r)

def parse_time(v):
    return datetime.fromisoformat(v.replace("Z", "+00:00"))

def main():
    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.19 -- AUDITORIA DO CICLO FORWARD")
    print("=" * 100)
    print(f"Posições abertas: {OPEN_FILE}")
    print(f"Ledger financeiro: {LEDGER_FILE}")
    print("Modo: AUDITORIA — NÃO ALTERA DADOS")
    print("CSV legado V8: NÃO UTILIZADO")
    print("-" * 100)

    open_fields, positions = load(OPEN_FILE)
    ledger_fields, trades = load(LEDGER_FILE)

    errors = []
    warnings = []

    if not LEDGER_FILE.exists():
        errors.append("ledger financeiro V9 não existe")
    elif ledger_fields != LEDGER_FIELDS:
        errors.append("schema do ledger V9 é diferente do schema esperado")

    if OPEN_FILE.exists() and positions and open_fields:
        required_open = {
            "signal_id", "scenario", "symbol", "entry_time",
            "entry_price", "quantity", "notional",
            "entry_fee_rate", "entry_fee",
            "slippage_entry_pct", "score", "confidence"
        }
        missing = sorted(required_open - set(open_fields))
        if missing:
            errors.append("campos ausentes nas posições abertas: " + ", ".join(missing))

    ids = set()
    duplicate_ids = 0
    for p in positions:
        sid = p.get("signal_id", "")
        if sid in ids:
            duplicate_ids += 1
        ids.add(sid)

        for field in ["entry_price", "quantity", "notional", "entry_fee"]:
            try:
                if float(p[field]) <= 0:
                    errors.append(f"posição {sid}: {field} <= 0")
            except Exception:
                errors.append(f"posição {sid}: {field} inválido")

        try:
            parse_time(p["entry_time"])
        except Exception:
            errors.append(f"posição {sid}: entry_time inválido")

    trade_ids = set()
    duplicate_trade_ids = 0
    ledger_net = 0.0

    for t in trades:
        tid = t.get("trade_id", "")
        if tid in trade_ids:
            duplicate_trade_ids += 1
        trade_ids.add(tid)

        for field in NUMERIC_FIELDS:
            try:
                float(t[field])
            except Exception:
                errors.append(f"trade {tid}: {field} inválido")

        try:
            if float(t["notional"]) <= 0:
                errors.append(f"trade {tid}: notional <= 0")
            ledger_net += float(t["net_pnl"])
        except Exception:
            pass

        try:
            if float(t["quantity"]) <= 0:
                errors.append(f"trade {tid}: quantity <= 0")
        except Exception:
            pass

        try:
            parse_time(t["entry_time"])
            parse_time(t["exit_time"])
        except Exception:
            errors.append(f"trade {tid}: timestamp inválido")

    if duplicate_ids:
        errors.append(f"signal_id duplicado em posições abertas: {duplicate_ids}")
    if duplicate_trade_ids:
        errors.append(f"trade_id duplicado no ledger: {duplicate_trade_ids}")

    # Uma posição aberta não deve aparecer como trade fechado.
    open_signal_ids = {p.get("signal_id") for p in positions}
    closed_trade_ids = {t.get("trade_id") for t in trades}
    overlap = 0
    for sid in open_signal_ids:
        if any(tid.startswith(str(sid) + "_") for tid in closed_trade_ids):
            overlap += 1
    if overlap:
        errors.append(f"posições abertas também aparecem fechadas: {overlap}")

    print(f"Posições abertas: {len(positions)}")
    print(f"Trades financeiros fechados: {len(trades)}")
    print(f"Net P&L acumulado do ledger: ${ledger_net:.8f}")
    print(f"Duplicidades abertas: {duplicate_ids}")
    print(f"Duplicidades no ledger: {duplicate_trade_ids}")

    if warnings:
        print("\nAVISOS:")
        for w in warnings:
            print(" -", w)

    print("\n" + "=" * 100)
    print("VEREDITO V9.19")
    print("=" * 100)

    if errors:
        print("NÃO APROVADA")
        print("Inconsistências:")
        for e in errors:
            print(" -", e)
        print("=" * 100)
        return 1

    print("APROVADA")
    print("Integridade estrutural do ciclo forward confirmada.")
    print("Nenhum dado foi inventado, corrigido ou composto.")
    print("=" * 100)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
