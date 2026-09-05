#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE LIVE TRADER (mainnet, DINHEIRO REAL)

Paralelo de binance_testnet_trader.py, apontado pro Binance Spot
MAINNET. Liga os sinais LONG reais do scanner_v3 (via
forward_signals.csv, só leitura) a ordens reais - compra/monitora/
vende com dinheiro de verdade.

FASE 3 do roteiro (ver memória do projeto): esta é a engenharia que
pode ser adiantada sem chave real. `main()` e `binance_live_loop.py`
tentam `load_env(ENV_FILE)` ANTES de qualquer chamada ccxt - sem
`.binance-live.env` (não criado nesta fase), falha limpo com
`FileNotFoundError` e retorna 1, sem jamais construir o exchange nem
tocar a rede. Esse é o mecanismo concreto que garante "sem chave, sem
ordem real" enquanto esta fase durar.

Isolado do paper trading v9 e do testnet de propósito:
    - Lê forward_signals.csv (só leitura).
    - Mantém posição/ledger PRÓPRIOS
      (data/binance_live_open_positions.csv, data/binance_live_trades.csv)
      - não compartilha estado com v9_17/v9_18/v9_21 nem com o testnet.
    - STOP_PCT/TARGET_PCT/MAX_HOLD_HOURS importados de
      paper_trading_v9_17.py (mesma fonte única que o testnet usa -
      nunca duplicar, já causou divergência real neste projeto).
    - Circuit breaker de drawdown (binance_live_circuit_breaker.py):
      antes de abrir posição nova, verifica se a perda acumulada desde
      um capital-base configurável passou do limite. Se sim, pula a
      abertura neste e nos próximos ciclos até reativação manual -
      posições já abertas continuam saindo normalmente por
      STOP/TARGET/TIME.

Sem cron - rodar manualmente ou via binance_live_loop.py:
    python3 src/binance_live_trader.py

Valor por posição / capital-base / limite de drawdown lidos de
data/binance_live_config.json a cada ciclo (não precisa reiniciar nada
pra mudar) - o portal (web/live.php) escreve esse arquivo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from binance_live_executor import (
    ENV_FILE,
    LOG_FILE,
    build_exchange,
    call_with_retry,
    load_env,
    log,
)
from binance_live_circuit_breaker import check_and_maybe_trip
from binance_testnet_trader import (
    append_csv,
    best_actionable_per_symbol,
    read_csv,
    write_csv,
)
from paper_trading_v9_17 import MAX_HOLD_HOURS, STOP_PCT, TARGET_PCT
from paper_trading_v9_21 import SIGNALS, parse_dt
from whatsapp_notify import send_whatsapp

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

LIVE_OPEN_FILE = DATA / "binance_live_open_positions.csv"
LIVE_LEDGER = DATA / "binance_live_trades.csv"

LIVE_OPEN_FIELDS = [
    "signal_id", "symbol", "entry_time", "entry_price", "quantity",
    "entry_cost_usdt", "buy_order_id", "score", "confidence",
    "target_reached",
]
LIVE_LEDGER_FIELDS = [
    "trade_id", "symbol", "entry_time", "exit_time", "entry_price",
    "exit_price", "quantity", "exit_reason", "gross_return_pct",
    "pnl_usdt", "buy_order_id", "sell_order_id",
]

LIVE_CONFIG_FILE = DATA / "binance_live_config.json"

MAX_POSITIONS_LIVE = 5
LIVE_NOTIONAL_USDT = 10.0            # default, usado se config.json faltar/for inválido
BASELINE_CAPITAL_USDT = 500.0        # placeholder - ajustar conscientemente antes da Fase 4
MAX_DRAWDOWN_PCT = 10.0              # placeholder - ajustar conscientemente antes da Fase 4

NOTIONAL_BOUNDS = (5.0, 100.0)
BASELINE_CAPITAL_BOUNDS = (10.0, 1_000_000.0)
MAX_DRAWDOWN_BOUNDS = (2.0, 50.0)


def _clamped(value, bounds, default):
    lo, hi = bounds
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if lo <= v <= hi:
        return v
    return default


def load_live_config() -> dict:
    defaults = {
        "notional_usdt": LIVE_NOTIONAL_USDT,
        "baseline_capital_usdt": BASELINE_CAPITAL_USDT,
        "max_drawdown_pct": MAX_DRAWDOWN_PCT,
    }
    try:
        raw = json.loads(LIVE_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defaults
    return {
        "notional_usdt": _clamped(raw.get("notional_usdt"), NOTIONAL_BOUNDS, defaults["notional_usdt"]),
        "baseline_capital_usdt": _clamped(
            raw.get("baseline_capital_usdt"), BASELINE_CAPITAL_BOUNDS, defaults["baseline_capital_usdt"]
        ),
        "max_drawdown_pct": _clamped(
            raw.get("max_drawdown_pct"), MAX_DRAWDOWN_BOUNDS, defaults["max_drawdown_pct"]
        ),
    }


def live_open_ids(open_rows: list[dict]) -> set[str]:
    return {r["signal_id"].strip() for r in open_rows if r.get("signal_id")}


def live_closed_ids(ledger_rows: list[dict]) -> set[str]:
    result = set()
    for r in ledger_rows:
        tid = r.get("trade_id", "").strip()
        if tid:
            result.add(tid.rsplit("_", 1)[0])
    return result


def monitor_open_positions(exchange) -> tuple[list[dict], int]:
    remaining = []
    closed_now = 0
    for pos in read_csv(LIVE_OPEN_FILE):
        symbol = pos["symbol"]
        try:
            ticker = call_with_retry(exchange.fetch_ticker, symbol)
            price = ticker["last"]
        except Exception as exc:
            log(f"AVISO monitor {symbol}: {type(exc).__name__}: {exc}")
            remaining.append(pos)
            continue

        entry = float(pos["entry_price"])
        change = price / entry - 1.0
        opened = parse_dt(pos["entry_time"])
        age_hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0

        reason = None
        if change <= -STOP_PCT:
            reason = "STOP"
        elif change >= TARGET_PCT:
            reason = "TARGET"
        elif age_hours >= MAX_HOLD_HOURS:
            reason = "TIME"

        if not reason:
            remaining.append(pos)
            continue

        try:
            quantity = float(exchange.amount_to_precision(symbol, float(pos["quantity"])))
            sell_order = call_with_retry(
                exchange.create_order, symbol, "market", "sell", quantity
            )
        except Exception as exc:
            log(
                f"AVISO: {symbol} bateu {reason} mas venda de fechamento "
                f"falhou ({type(exc).__name__}: {exc}) - mantendo posição "
                "aberta pra tentar de novo no próximo ciclo."
            )
            remaining.append(pos)
            continue

        fill_price = sell_order.get("average") or sell_order.get("price") or price
        gross_return_pct = (float(fill_price) / entry - 1.0) * 100.0
        exit_time = datetime.now(timezone.utc).isoformat()

        entry_cost = (pos.get("entry_cost_usdt") or "").strip()
        entry_cost_usdt = float(entry_cost) if entry_cost else entry * quantity
        exit_cost_usdt = float(
            sell_order.get("cost") or (float(fill_price) * quantity)
        )
        pnl_usdt = exit_cost_usdt - entry_cost_usdt

        append_csv(LIVE_LEDGER, LIVE_LEDGER_FIELDS, {
            "trade_id": f"{pos['signal_id']}_{exit_time}",
            "symbol": symbol,
            "entry_time": pos["entry_time"],
            "exit_time": exit_time,
            "entry_price": pos["entry_price"],
            "exit_price": f"{float(fill_price):.12f}",
            "quantity": pos["quantity"],
            "exit_reason": reason,
            "gross_return_pct": f"{gross_return_pct:.6f}",
            "pnl_usdt": f"{pnl_usdt:.6f}",
            "buy_order_id": pos.get("buy_order_id", ""),
            "sell_order_id": sell_order.get("id", ""),
        })
        log(
            f"[LIVE] CLOSE {symbol:12s} {reason:6s} "
            f"gross={gross_return_pct:+.4f}% pnl=${pnl_usdt:+.4f} "
            f"sell_order={sell_order.get('id')}"
        )
        send_whatsapp(
            f"[LIVE] {symbol} fechado por {reason}: "
            f"{gross_return_pct:+.2f}% (${pnl_usdt:+.2f} dinheiro real)"
        )
        closed_now += 1

    return remaining, closed_now


def open_new_positions(
    exchange, remaining: list[dict], notional_usdt: float
) -> list[dict]:
    slots = max(0, MAX_POSITIONS_LIVE - len(remaining))
    if slots <= 0:
        return remaining

    open_rows = read_csv(LIVE_OPEN_FILE)
    ledger_rows = read_csv(LIVE_LEDGER)
    open_ids = live_open_ids(open_rows)
    closed_ids = live_closed_ids(ledger_rows)
    open_symbols = {p["symbol"].strip().upper() for p in remaining}

    candidates = best_actionable_per_symbol(open_ids, closed_ids)

    for sym, signal in candidates.items():
        if slots <= 0:
            break
        if sym in open_symbols:
            continue

        try:
            ticker = call_with_retry(exchange.fetch_ticker, sym)
            price = ticker["last"]
            raw_amount = notional_usdt / price
            amount = float(exchange.amount_to_precision(sym, raw_amount))
            buy_order = call_with_retry(
                exchange.create_order, sym, "market", "buy", amount
            )
        except ccxt.BadSymbol:
            continue
        except Exception as exc:
            log(f"[LIVE] AVISO abertura {sym}: {type(exc).__name__}: {exc}")
            continue

        filled = float(buy_order.get("filled") or 0.0)
        if filled <= 0:
            log(f"[LIVE] AVISO {sym}: ordem de compra não preencheu, ignorando.")
            continue

        fill_price = buy_order.get("average") or buy_order.get("price") or price
        entry_cost_usdt = float(buy_order.get("cost") or (float(fill_price) * filled))
        entry_time = datetime.now(timezone.utc).isoformat()

        remaining.append({
            "signal_id": signal["signal_id"],
            "symbol": sym,
            "entry_time": entry_time,
            "entry_price": f"{float(fill_price):.12f}",
            "quantity": f"{filled:.12f}",
            "entry_cost_usdt": f"{entry_cost_usdt:.6f}",
            "buy_order_id": str(buy_order.get("id", "")),
            "score": signal.get("score", ""),
            "confidence": signal.get("confidence", ""),
            "target_reached": "0",
        })
        open_symbols.add(sym)
        slots -= 1
        log(
            f"[LIVE] OPEN  {sym:12s} entry={fill_price} qty={filled} "
            f"buy_order={buy_order.get('id')}"
        )

    return remaining


def run_cycle(exchange) -> tuple[int, int, bool]:
    """Um ciclo completo: monitora/fecha posições (sempre), checa o
    circuit breaker, e só abre posição nova se não estiver travado."""
    cfg = load_live_config()
    remaining, closed_now = monitor_open_positions(exchange)

    ledger_rows = read_csv(LIVE_LEDGER)
    cb_state = check_and_maybe_trip(
        ledger_rows, cfg["baseline_capital_usdt"], cfg["max_drawdown_pct"]
    )
    halted = bool(cb_state["tripped"])

    if not halted:
        remaining = open_new_positions(exchange, remaining, cfg["notional_usdt"])
    else:
        log("[LIVE] CIRCUIT BREAKER ATIVO: pulando abertura de novas posições neste ciclo.")

    write_csv(LIVE_OPEN_FILE, LIVE_OPEN_FIELDS, remaining)
    return closed_now, len(remaining), halted


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - BINANCE LIVE TRADER")
    print("=" * 100)
    print("AMBIENTE: BINANCE SPOT MAINNET - DINHEIRO REAL")
    print(f"Sinais: {SIGNALS}")
    print(f"STOP / TARGET / MAX_HOLD: {STOP_PCT:.2%} / {TARGET_PCT:.2%} / {MAX_HOLD_HOURS}h")
    cfg = load_live_config()
    print(
        f"Notional por posição: ${cfg['notional_usdt']:.2f} | "
        f"Máx. posições: {MAX_POSITIONS_LIVE} | "
        f"Capital-base: ${cfg['baseline_capital_usdt']:.2f} | "
        f"Limite drawdown: {cfg['max_drawdown_pct']:.1f}%"
    )
    print("-" * 100)

    try:
        env = load_env(ENV_FILE)
        exchange = build_exchange(env)
        exchange.load_markets()
    except Exception as exc:
        log(f"ERRO de configuração: {exc}")
        return 1

    closed_now, open_count, halted = run_cycle(exchange)

    log(
        f"[LIVE] CICLO concluído: {closed_now} fechada(s), "
        f"{open_count} posição(ões) aberta(s)."
        + (" CIRCUIT BREAKER ATIVO." if halted else "")
    )
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
