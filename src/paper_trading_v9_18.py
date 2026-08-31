#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.18
Monitoramento e fechamento de posições forward.

Objetivo:
- Ler posições abertas criadas pela V9.17.
- Buscar preço atual via Binance/CCXT.
- Aplicar STOP, TARGET e TEMPO MÁXIMO.
- Fechar somente posições que realmente atendam uma condição.
- Gravar o trade fechado no ledger financeiro V9.
- Nunca usar o CSV legado V8 para inventar dados.
- PAPER ONLY: nenhuma ordem real.

Hipóteses financeiras da cadeia V9:
  fee por lado: 0.10%
  slippage por lado: 0.10%
  STOP: 4%
  TARGET: 6%
  tempo máximo: 24h
"""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import ccxt
except ImportError:
    ccxt = None

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OPEN_FILE = DATA / "paper_trading_v9_open_positions.csv"
LEDGER_FILE = DATA / "paper_trading_v9_financial_trades.csv"

FEE_RATE = 0.001
SLIPPAGE_PCT = 0.001

# STOP_PCT/TARGET_PCT/OPEN_FIELDS importados de paper_trading_v9_17.py
# (fonte única) - antes eram duplicados aqui com valor próprio, o que
# já causou divergência real entre os dois monitores. Ver STOP_PCT em
# v9_17.py para o histórico da mudança de 4%/8% para 5%/6%, e o
# comentário acima de target_reached lá pra regra de trava de lucro.
from paper_trading_v9_17 import OPEN_FIELDS, STOP_PCT, TARGET_PCT

MAX_HOURS = 24.0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def load_csv(path: Path):
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames or [], rows


def write_csv(path: Path, fields, rows):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def ensure_ledger():
    fields, _ = load_csv(LEDGER_FILE)
    required = [
        "trade_id", "scenario", "symbol", "entry_time", "exit_time",
        "entry_price", "exit_price", "quantity", "notional",
        "entry_fee_rate", "exit_fee_rate", "entry_fee", "exit_fee",
        "slippage_entry_pct", "slippage_exit_pct",
        "gross_return_pct", "net_return_pct",
        "gross_pnl", "net_pnl", "exit_reason", "holding_hours"
    ]
    if fields != required:
        # Só cria/corrige schema quando o arquivo está vazio ou ausente.
        # Não sobrescreve um ledger financeiro existente com conteúdo.
        _, rows = load_csv(LEDGER_FILE)
        if rows:
            raise RuntimeError(
                "Ledger V9 existente possui schema inesperado; "
                "nenhum dado foi sobrescrito."
            )
        write_csv(LEDGER_FILE, required, [])
    return required


def fetch_prices(symbols):
    if not symbols:
        return {}
    if ccxt is None:
        raise RuntimeError("ccxt não está instalado no ambiente atual.")

    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    tickers = exchange.fetch_tickers(symbols)
    result = {}
    for symbol in symbols:
        ticker = tickers.get(symbol)
        if ticker:
            last = ticker.get("last")
            if last is not None and float(last) > 0:
                result[symbol] = float(last)
    return result


def close_position(pos, market_price, reason, closed_at):
    entry_price = float(pos["entry_price"])
    qty = float(pos["quantity"])
    notional = float(pos["notional"])

    # Preço efetivo de saída com slippage adverso para LONG.
    exit_price = market_price * (1.0 - SLIPPAGE_PCT)

    gross_pnl = (exit_price - entry_price) * qty
    gross_return_pct = ((exit_price / entry_price) - 1.0) * 100.0

    entry_fee = float(pos["entry_fee"])
    exit_notional = exit_price * qty
    exit_fee = exit_notional * FEE_RATE

    net_pnl = gross_pnl - entry_fee - exit_fee
    # Retorno líquido sobre o notional originalmente alocado.
    net_return_pct = (net_pnl / notional) * 100.0

    holding_hours = (
        closed_at - parse_dt(pos["entry_time"])
    ).total_seconds() / 3600.0

    trade_id = (
        f"{pos['signal_id']}_"
        f"{closed_at.strftime('%Y%m%d%H%M%S')}"
    )

    return {
        "trade_id": trade_id,
        "scenario": pos["scenario"],
        "symbol": pos["symbol"],
        "entry_time": pos["entry_time"],
        "exit_time": fmt_dt(closed_at),
        "entry_price": f"{entry_price:.12f}",
        "exit_price": f"{exit_price:.12f}",
        "quantity": f"{qty:.12f}",
        "notional": f"{notional:.8f}",
        "entry_fee_rate": f"{float(pos['entry_fee_rate']):.8f}",
        "exit_fee_rate": f"{FEE_RATE:.8f}",
        "entry_fee": f"{entry_fee:.8f}",
        "exit_fee": f"{exit_fee:.8f}",
        "slippage_entry_pct": f"{float(pos['slippage_entry_pct']):.8f}",
        "slippage_exit_pct": f"{SLIPPAGE_PCT:.8f}",
        "gross_return_pct": f"{gross_return_pct:.8f}",
        "net_return_pct": f"{net_return_pct:.8f}",
        "gross_pnl": f"{gross_pnl:.8f}",
        "net_pnl": f"{net_pnl:.8f}",
        "exit_reason": reason,
        "holding_hours": f"{holding_hours:.6f}",
    }


def should_close(pos, market_price, current_time):
    # Revertido em 2026-08-31 (pedido do usuário) - a "trava de lucro"
    # voltou a ser venda imediata ao bater TARGET_PCT.
    entry = float(pos["entry_price"])
    ret = market_price / entry - 1.0
    age_h = (current_time - parse_dt(pos["entry_time"])).total_seconds() / 3600.0

    if ret <= -STOP_PCT:
        return "STOP"
    if ret >= TARGET_PCT:
        return "TARGET"
    if age_h >= MAX_HOURS:
        return "TIME"
    return None


def main():
    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.18 -- MONITOR / CLOSE")
    print("=" * 100)
    print(f"Posições abertas:    {OPEN_FILE}")
    print(f"Ledger financeiro:   {LEDGER_FILE}")
    print(f"Fee saída:            {FEE_RATE:.3%} [HIPÓTESE V9]")
    print(f"Slippage saída:      {SLIPPAGE_PCT:.3%} [HIPÓTESE V9]")
    print(f"STOP / TARGET:        {STOP_PCT:.2%} / {TARGET_PCT:.2%}")
    print(f"Tempo máximo:         {MAX_HOURS:.0f}h")
    print("Modo: PAPER ONLY")
    print("Ordens reais: NÃO")
    print("CSV legado V8: NÃO UTILIZADO")
    print("-" * 100)

    ledger_fields = ensure_ledger()
    open_fields, positions = load_csv(OPEN_FILE)

    if not positions:
        print("Nenhuma posição aberta. Nada a fechar.")
        print("=" * 100)
        return

    symbols = sorted({p["symbol"] for p in positions})
    prices = fetch_prices(symbols)
    current = now_utc()

    remaining = []
    closed = []

    for pos in positions:
        symbol = pos["symbol"]
        price = prices.get(symbol)

        if price is None:
            print(f"SKIP {symbol:<12} preço atual indisponível")
            remaining.append(pos)
            continue

        reason = should_close(pos, price, current)

        entry = float(pos["entry_price"])
        raw_ret = (price / entry - 1.0) * 100.0
        age = (current - parse_dt(pos["entry_time"])).total_seconds() / 3600.0

        if reason:
            trade = close_position(pos, price, reason, current)
            closed.append(trade)
            print(
                f"CLOSE {symbol:<12} price={price:.8f} "
                f"ret={raw_ret:+.3f}% age={age:.2f}h "
                f"reason={reason:<6} net=${float(trade['net_pnl']):+.4f}"
            )
        else:
            remaining.append(pos)
            print(
                f"HOLD  {symbol:<12} price={price:.8f} "
                f"ret={raw_ret:+.3f}% age={age:.2f}h"
            )

    # OPEN_FIELDS (de v9_17.py) em vez do open_fields lido do arquivo -
    # garante a coluna target_reached mesmo se o CSV existente for de
    # antes dessa mudança de schema.
    write_csv(OPEN_FILE, OPEN_FIELDS, remaining)

    if closed:
        _, ledger_rows = load_csv(LEDGER_FILE)
        ledger_rows.extend(closed)
        write_csv(LEDGER_FILE, ledger_fields, ledger_rows)

    print("-" * 100)
    print(f"Posições antes:      {len(positions)}")
    print(f"Novos CLOSE:         {len(closed)}")
    print(f"Posições abertas:    {len(remaining)}")
    print(f"Trades no ledger:    {len(load_csv(LEDGER_FILE)[1])}")
    print("=" * 100)
    print("V9.18 concluiu um ciclo PAPER. Nenhuma ordem real foi enviada.")
    print("=" * 100)


if __name__ == "__main__":
    main()
