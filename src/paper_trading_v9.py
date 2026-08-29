#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9
Motor de paper trading financeiro, sem ordens reais.

Objetivo:
- executar um dataset de sinais/trades cronologicamente;
- controlar capital e posições simultâneas;
- aplicar notional, taxas e slippage de forma explícita;
- gerar uma equity curve válida para a simulação;
- nunca transformar o CSV legado V8 em fato histórico.

Uso:
  python3 src/paper_trading_v9.py
  python3 src/paper_trading_v9.py --trades data/paper_trading_v8_trades.csv
  python3 src/paper_trading_v9.py --capital 1000 --notional 100 --max-positions 10 \
      --fee-rate 0.001 --slippage 0.001
"""

from __future__ import annotations
import argparse, csv, math, os
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import defaultdict

@dataclass
class Trade:
    row: int
    scenario: str
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    return_pct: float
    score: float | None
    confidence: float | None
    exit_reason: str

def dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    x = datetime.fromisoformat(s)
    if x.tzinfo is None:
        x = x.replace(tzinfo=timezone.utc)
    return x.astimezone(timezone.utc)

def num(x):
    try:
        y = float(x)
        return y if math.isfinite(y) else None
    except Exception:
        return None

def load(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    req = {"symbol","entry_time","exit_time","entry_price","exit_price","return_pct"}
    if not rows:
        raise RuntimeError("CSV vazio.")
    miss = req - set(rows[0])
    if miss:
        raise RuntimeError("Colunas ausentes: " + ", ".join(sorted(miss)))
    out = []
    for i, r in enumerate(rows, 2):
        try:
            ep, xp = float(r["entry_price"]), float(r["exit_price"])
            if ep <= 0 or xp <= 0:
                continue
            out.append(Trade(
                i, r.get("scenario","LEGACY"), r["symbol"].strip().upper(),
                dt(r["entry_time"]), dt(r["exit_time"]), ep, xp,
                float(r["return_pct"]), num(r.get("score")),
                num(r.get("confidence")), r.get("exit_reason","")
            ))
        except Exception:
            continue
    return sorted(out, key=lambda x: (x.entry_time, x.exit_time, x.row))

def fee(notional, rate):
    return abs(notional) * rate

def simulate(trades, capital, notional, max_positions, fee_rate, slip):
    cash = float(capital)
    open_pos = []
    closed = []
    equity = [(None, cash)]
    rejected = 0

    for t in trades:
        # First close positions whose exit is at/before this entry.
        still = []
        for p in open_pos:
            if p["exit_time"] <= t.entry_time:
                cash += p["net_pnl"]
                closed.append(p)
                equity.append((p["exit_time"], cash))
            else:
                still.append(p)
        open_pos = still

        if len(open_pos) >= max_positions:
            rejected += 1
            continue
        if cash <= 0:
            rejected += 1
            continue

        # Notional is a hypothesis for V9 simulation, never historical fact.
        n = min(float(notional), cash)
        entry_exec = t.entry_price * (1.0 + slip)
        exit_exec = t.exit_price * (1.0 - slip)
        qty = n / entry_exec

        entry_fee = fee(n, fee_rate)
        gross_pnl = qty * (exit_exec - entry_exec)
        exit_notional = qty * exit_exec
        exit_fee = fee(exit_notional, fee_rate)
        net_pnl = gross_pnl - entry_fee - exit_fee
        net_return = (net_pnl / n) * 100.0 if n else 0.0

        open_pos.append({
            "trade": t, "scenario": t.scenario, "symbol": t.symbol,
            "entry_time": t.entry_time, "exit_time": t.exit_time,
            "notional": n, "quantity": qty,
            "entry_price": t.entry_price, "exit_price": t.exit_price,
            "entry_exec": entry_exec, "exit_exec": exit_exec,
            "entry_fee": entry_fee, "exit_fee": exit_fee,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl, "net_return_pct": net_return,
            "exit_reason": t.exit_reason
        })

    for p in sorted(open_pos, key=lambda x: x["exit_time"]):
        cash += p["net_pnl"]
        closed.append(p)
        equity.append((p["exit_time"], cash))

    # Equity is event-driven cash after closed positions; capital reserved by
    # open positions is not double-counted as cash. Final result is valid for
    # this hypothetical portfolio model.
    if not closed:
        return closed, rejected, capital, 0.0
    peak = capital
    max_dd = 0.0
    running = capital
    for _, val in sorted(equity, key=lambda x: (x[0] or datetime.min.replace(tzinfo=timezone.utc))):
        running = val
        peak = max(peak, running)
        if peak:
            max_dd = min(max_dd, (running / peak - 1.0) * 100.0)
    return closed, rejected, cash, max_dd

def write_csv(path, rows):
    if not rows:
        return
    fields = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", default="data/paper_trading_v8_trades.csv")
    ap.add_argument("--out", default="data/paper_trading_v9_trades.csv")
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--notional", type=float, default=100.0)
    ap.add_argument("--max-positions", type=int, default=10)
    ap.add_argument("--fee-rate", type=float, default=0.001)
    ap.add_argument("--slippage", type=float, default=0.001)
    args = ap.parse_args()

    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9 -- MOTOR FINANCEIRO")
    print("="*100)
    print(f"Trades:             {args.trades}")
    print(f"Capital inicial:    ${args.capital:,.2f}")
    print(f"Notional/trade:     ${args.notional:,.2f}  [HIPÓTESE V9]")
    print(f"Máx. posições:     {args.max_positions}")
    print(f"Fee por lado:       {args.fee_rate*100:.3f}%  [HIPÓTESE V9]")
    print(f"Slippage por lado:  {args.slippage*100:.3f}%  [HIPÓTESE V9]")
    print("Ordens reais:       NÃO")
    print("-"*100)

    trades = load(args.trades)
    closed, rejected, final, dd = simulate(
        trades, args.capital, args.notional, args.max_positions,
        args.fee_rate, args.slippage
    )

    rows = []
    for p in closed:
        rows.append({
            "trade_row": p["trade"].row,
            "scenario": p["scenario"], "symbol": p["symbol"],
            "entry_time": p["entry_time"].isoformat(),
            "exit_time": p["exit_time"].isoformat(),
            "entry_price": p["entry_price"], "exit_price": p["exit_price"],
            "entry_exec": p["entry_exec"], "exit_exec": p["exit_exec"],
            "quantity": p["quantity"], "notional": p["notional"],
            "entry_fee": p["entry_fee"], "exit_fee": p["exit_fee"],
            "gross_pnl": p["gross_pnl"], "net_pnl": p["net_pnl"],
            "net_return_pct": p["net_return_pct"],
            "exit_reason": p["exit_reason"]
        })
    write_csv(args.out, rows)

    total_net = sum(float(x["net_pnl"]) for x in rows)
    wins = sum(1 for x in rows if float(x["net_pnl"]) > 0)
    losses = sum(1 for x in rows if float(x["net_pnl"]) < 0)
    gross_profit = sum(float(x["net_pnl"]) for x in rows if float(x["net_pnl"]) > 0)
    gross_loss = -sum(float(x["net_pnl"]) for x in rows if float(x["net_pnl"]) < 0)
    pf = gross_profit / gross_loss if gross_loss else float("inf")

    print("\nRESULTADO DA SIMULAÇÃO V9")
    print(f"Trades aceitos:     {len(rows)}")
    print(f"Trades rejeitados:  {rejected}")
    print(f"Win rate:           {wins/len(rows)*100:.2f}%" if rows else "Win rate:           n/a")
    print(f"Profit Factor:      {pf:.3f}")
    print(f"Resultado líquido:  ${total_net:,.2f}")
    print(f"Capital final:      ${final:,.2f}")
    print(f"Drawdown:           {dd:.2f}%")
    print(f"Arquivo:            {args.out}")
    print("\nIMPORTANTE: taxas, notional e slippage acima são hipóteses da V9.")
    print("Eles NÃO são recuperados do CSV legado V8.")
    print("="*100)

if __name__ == "__main__":
    main()
