#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.17
FORWARD TRADE EXECUTOR

Scanner -> forward_signals.csv -> V9.17 -> open/monitor/close -> financial ledger.

PAPER ONLY. Nenhuma ordem real.
Não utiliza retornos, P&L ou taxas do CSV legado V8.

Ciclo:
  1) sinais LONG novos são abertos com notional fixo hipotético;
  2) posições abertas são monitoradas por preço atual;
  3) saída ocorre por STOP, TARGET ou TIME;
  4) somente trades fechados são gravados no ledger financeiro V9.

Uso:
  python3 src/paper_trading_v9_17.py
"""

from __future__ import annotations
import csv
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ccxt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SIGNALS = DATA / "forward_signals.csv"
LEDGER = DATA / "paper_trading_v9_financial_trades.csv"
OPEN_FILE = DATA / "paper_trading_v9_open_positions.csv"

# Hipóteses explícitas da V9.17.
CAPITAL = 1000.0
NOTIONAL = 100.0
MAX_POSITIONS = 10
ENTRY_FEE_RATE = 0.001
EXIT_FEE_RATE = 0.001
SLIPPAGE_ENTRY_PCT = 0.001
SLIPPAGE_EXIT_PCT = 0.001

# Saídas iniciais conservadoras. Não são derivadas do V8.
STOP_PCT = 0.04
TARGET_PCT = 0.08
MAX_HOLD_HOURS = 24

SIGNAL_FIELDS = {
    "signal_id", "scenario", "symbol", "entry_time", "entry_price",
    "timeframe", "score", "confidence", "signal"
}

LEDGER_FIELDS = [
    "trade_id", "scenario", "symbol", "entry_time", "exit_time",
    "entry_price", "exit_price", "quantity", "notional",
    "entry_fee_rate", "exit_fee_rate", "entry_fee", "exit_fee",
    "slippage_entry_pct", "slippage_exit_pct",
    "gross_return_pct", "net_return_pct", "gross_pnl", "net_pnl",
    "exit_reason", "holding_hours"
]

OPEN_FIELDS = [
    "signal_id", "scenario", "symbol", "entry_time", "entry_price",
    "quantity", "notional", "entry_fee_rate", "entry_fee",
    "slippage_entry_pct", "score", "confidence"
]


def now_utc():
    return datetime.now(timezone.utc)


def parse_dt(s):
    x = str(s).strip()
    if x.endswith("Z"):
        x = x[:-1] + "+00:00"
    d = datetime.fromisoformat(x)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def read_csv(path):
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def append_csv(path, fields, row):
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerow(row)


def validate_signals(rows):
    valid = []
    for r in rows:
        if not SIGNAL_FIELDS.issubset(r):
            continue
        try:
            if r["signal"].strip().upper() != "LONG":
                continue
            if not r["symbol"].strip():
                continue
            if num(r["entry_price"]) is None or num(r["entry_price"]) <= 0:
                continue
            parse_dt(r["entry_time"])
            valid.append(r)
        except Exception:
            continue
    return valid


def fetch_price(exchange, symbol):
    ticker = exchange.fetch_ticker(symbol)
    p = num(ticker.get("last"))
    if p is None or p <= 0:
        raise RuntimeError(f"preço inválido para {symbol}")
    return p


def load_open():
    rows = read_csv(OPEN_FILE)
    return rows


def open_trade(signal):
    p = num(signal["entry_price"])

    # Slippage de entrada desfavorável para uma posição LONG.
    effective_entry = p * (1.0 + SLIPPAGE_ENTRY_PCT)
    quantity = NOTIONAL / effective_entry
    fee = NOTIONAL * ENTRY_FEE_RATE

    return {
        "signal_id": signal["signal_id"],
        "scenario": signal["scenario"],
        "symbol": signal["symbol"].strip().upper(),
        "entry_time": parse_dt(signal["entry_time"]).isoformat(),
        "entry_price": f"{effective_entry:.12f}",
        "quantity": f"{quantity:.12f}",
        "notional": f"{NOTIONAL:.8f}",
        "entry_fee_rate": f"{ENTRY_FEE_RATE:.8f}",
        "entry_fee": f"{fee:.8f}",
        "slippage_entry_pct": f"{SLIPPAGE_ENTRY_PCT:.8f}",
        "score": signal.get("score", ""),
        "confidence": signal.get("confidence", ""),
    }


def close_trade(pos, exit_price, reason, exit_time):
    entry = float(pos["entry_price"])
    qty = float(pos["quantity"])
    notional = float(pos["notional"])
    entry_fee = float(pos["entry_fee"])

    # Slippage de saída desfavorável para LONG.
    effective_exit = exit_price * (1.0 - SLIPPAGE_EXIT_PCT)
    gross_pnl = qty * (effective_exit - entry)
    exit_notional = qty * effective_exit
    exit_fee = exit_notional * EXIT_FEE_RATE

    net_pnl = gross_pnl - entry_fee - exit_fee
    gross_return = (effective_exit / entry - 1.0) * 100.0
    net_return = (net_pnl / notional) * 100.0

    et = parse_dt(pos["entry_time"])
    holding = max(0.0, (exit_time - et).total_seconds() / 3600.0)

    trade_id = f'{pos["signal_id"]}_{exit_time.strftime("%Y%m%d%H%M%S")}'

    return {
        "trade_id": trade_id,
        "scenario": pos["scenario"],
        "symbol": pos["symbol"],
        "entry_time": et.isoformat(),
        "exit_time": exit_time.isoformat(),
        "entry_price": f"{entry:.12f}",
        "exit_price": f"{effective_exit:.12f}",
        "quantity": f"{qty:.12f}",
        "notional": f"{notional:.8f}",
        "entry_fee_rate": f"{ENTRY_FEE_RATE:.8f}",
        "exit_fee_rate": f"{EXIT_FEE_RATE:.8f}",
        "entry_fee": f"{entry_fee:.8f}",
        "exit_fee": f"{exit_fee:.8f}",
        "slippage_entry_pct": f"{SLIPPAGE_ENTRY_PCT:.8f}",
        "slippage_exit_pct": f"{SLIPPAGE_EXIT_PCT:.8f}",
        "gross_return_pct": f"{gross_return:.8f}",
        "net_return_pct": f"{net_return:.8f}",
        "gross_pnl": f"{gross_pnl:.8f}",
        "net_pnl": f"{net_pnl:.8f}",
        "exit_reason": reason,
        "holding_hours": f"{holding:.8f}",
    }


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.17 -- FORWARD TRADE EXECUTOR")
    print("=" * 100)
    print(f"Sinais:                 {SIGNALS}")
    print(f"Posições abertas:       {OPEN_FILE}")
    print(f"Ledger financeiro:      {LEDGER}")
    print(f"Capital referência:     ${CAPITAL:,.2f}")
    print(f"Notional por trade:     ${NOTIONAL:,.2f} [HIPÓTESE V9.17]")
    print(f"Máx. posições:          {MAX_POSITIONS}")
    print(f"Fee entrada/saída:      {ENTRY_FEE_RATE:.3%} / {EXIT_FEE_RATE:.3%} [HIPÓTESE]")
    print(f"Slippage entrada/saída:  {SLIPPAGE_ENTRY_PCT:.3%} / {SLIPPAGE_EXIT_PCT:.3%} [HIPÓTESE]")
    print(f"STOP / TARGET:           {STOP_PCT:.2%} / {TARGET_PCT:.2%}")
    print(f"Tempo máximo:            {MAX_HOLD_HOURS}h")
    print("Modo: PAPER ONLY")
    print("Ordens reais: NÃO")
    print("CSV legado V8: NÃO UTILIZADO")
    print("-" * 100)

    signals = validate_signals(read_csv(SIGNALS))
    open_rows = load_open()

    # Não reabre um sinal que já tenha posição aberta ou trade fechado.
    open_ids = {r.get("signal_id") for r in open_rows}
    ledger_rows = read_csv(LEDGER)
    closed_ids = {
        # trade_id = f"{signal_id}_{exit_timestamp}"; signal_id pode
        # conter "_", então removemos só o sufixo de timestamp (sem "_").
        r.get("trade_id", "").rsplit("_", 1)[0]
        for r in ledger_rows if r.get("trade_id")
    }

    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })

    # 1. Monitorar posições abertas.
    remaining = []
    closed_now = 0

    for pos in open_rows:
        try:
            price = fetch_price(exchange, pos["symbol"])
            entry = float(pos["entry_price"])
            change = price / entry - 1.0
            opened = parse_dt(pos["entry_time"])
            age = (now_utc() - opened).total_seconds() / 3600.0

            reason = None
            if change <= -STOP_PCT:
                reason = "STOP"
            elif change >= TARGET_PCT:
                reason = "TARGET"
            elif age >= MAX_HOLD_HOURS:
                reason = "TIME"

            if reason:
                trade = close_trade(pos, price, reason, now_utc())
                append_csv(LEDGER, LEDGER_FIELDS, trade)
                closed_now += 1
                print(
                    f"CLOSE {pos['symbol']:12s} {reason:6s} "
                    f"net={float(trade['net_return_pct']):+.4f}%"
                )
            else:
                remaining.append(pos)
        except Exception as exc:
            print(f"AVISO monitor {pos.get('symbol')}: {exc}")
            remaining.append(pos)

    # 2. Abrir sinais novos, sem inventar entradas.
    slots = max(0, MAX_POSITIONS - len(remaining))
    opened_now = 0

    expired_now = 0

    for signal in signals:
        sid = signal["signal_id"]
        if sid in open_ids or sid in closed_ids:
            continue
        if slots <= 0:
            break

        # Um sinal cujo entry_time já passou de MAX_HOLD_HOURS nunca
        # deveria virar posição nova: ela "nasceria" já além do tempo
        # máximo de holding, e o próximo monitor a fecharia por TIME
        # usando um preço de entrada de dias atrás como se fosse uma
        # decisão tomada agora. Isso já aconteceu de verdade (backlog
        # de sinais represado pelo bug do preflight, corrigido depois,
        # mas os sinais antigos continuaram elegíveis pra abrir aqui).
        try:
            signal_age_hours = (
                now_utc() - parse_dt(signal["entry_time"])
            ).total_seconds() / 3600.0
        except Exception:
            signal_age_hours = 0.0

        if signal_age_hours >= MAX_HOLD_HOURS:
            expired_now += 1
            continue

        try:
            pos = open_trade(signal)
            remaining.append(pos)
            open_ids.add(sid)
            slots -= 1
            opened_now += 1
            print(
                f"OPEN  {pos['symbol']:12s} "
                f"entry={float(pos['entry_price']):.8f} "
                f"notional=${NOTIONAL:.2f}"
            )
        except Exception as exc:
            print(f"AVISO abertura {signal.get('symbol')}: {exc}")

    write_csv(OPEN_FILE, OPEN_FIELDS, remaining)

    print("-" * 100)
    print(f"Sinais válidos:         {len(signals)}")
    print(f"Posições antes:         {len(open_rows)}")
    print(f"Novos OPEN:             {opened_now}")
    print(f"Sinais expirados (>={MAX_HOLD_HOURS}h, não abertos): {expired_now}")
    print(f"Novos CLOSE:            {closed_now}")
    print(f"Posições abertas agora: {len(remaining)}")
    print(f"Trades no ledger:       {len(read_csv(LEDGER))}")
    print("=" * 100)
    print("V9.17 concluiu um ciclo PAPER. Nenhuma ordem real foi enviada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
