#!/usr/bin/env python3
"""
CRYPTO RADAR - EXPLORAÇÃO DE STOP/TARGET COM TREINO/TESTE DE VERDADE

Investiga se algum STOP_PCT/TARGET_PCT diferente do atual (4%/8%,
paper_trading_v9_17.py) resolve o problema da mediana de retorno
negativa - sem repetir o erro de overfitting da linhagem v8 antiga.

Metodologia (walk-forward simples, com embargo):
  1. Divide o histórico cronologicamente: TREINO (primeiros ~31 dias),
     EMBARGO de 24h (mesmo valor de MAX_HOLD_HOURS - evita que um
     trade "vaze" através da fronteira), TESTE (resto, ~10-11 dias).
  2. Testa uma grade PEQUENA e fixa de combinações (4 stops x 4
     targets = 16, incluindo o par atual 4%/8%) SÓ no treino.
  3. Só avança pro teste os candidatos cuja mediana no treino supera a
     do par atual E que têm N>=30 no treino E PF>=1.0 (filtro de
     sanidade, não de otimização).
  4. Reporta o par atual e os candidatos aprovados rodando no TESTE
     (dado nunca usado pra escolher nada) - o veredito final é sempre
     sobre o teste, nunca sobre o treino.

Isto NÃO otimiza score, MAX_HOLD_HOURS, MAX_POSITIONS, fees ou
slippage - só STOP_PCT/TARGET_PCT, e só reporta o que sobrevive ao
teste fora da amostra. Se nada bater o par atual no teste, a conclusão
honesta é "nenhuma melhoria robusta encontrada", não forçar uma escolha.

Uso:
  python3 src/v9_parameter_walkforward.py
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd

from paper_trading_v9_17 import (
    CAPITAL,
    ENTRY_FEE_RATE,
    EXIT_FEE_RATE,
    MAX_HOLD_HOURS,
    MAX_POSITIONS,
    NOTIONAL,
    SLIPPAGE_ENTRY_PCT,
    SLIPPAGE_EXIT_PCT,
    STOP_PCT as BASELINE_STOP_PCT,
    TARGET_PCT as BASELINE_TARGET_PCT,
)
from v9_historical_backtest import Candidate, load_candidates, fetch_full_history

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "crypto_radar.db"
OUTPUT_CSV = ROOT / "data" / "v9_parameter_walkforward_results.csv"

TIMEFRAME = "1h"
EMBARGO_HOURS = MAX_HOLD_HOURS

# Grade pequena e fixa - inclui o par de produção pra comparação direta.
STOP_GRID = [0.03, 0.04, 0.05, 0.06]
TARGET_GRID = [0.06, 0.08, 0.10, 0.12]


@dataclass
class Position:
    symbol: str
    entry_time: datetime
    entry_price: float
    quantity: float
    entry_fee: float


@dataclass
class Trade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    net_pnl: float
    net_return_pct: float
    exit_reason: str
    holding_hours: float


def simulate(
    candidates: list[Candidate],
    price_history: dict[str, pd.DataFrame],
    stop_pct: float,
    target_pct: float,
) -> list[Trade]:

    by_hour: dict[datetime, list[Candidate]] = {}
    for c in candidates:
        by_hour.setdefault(c.entry_time, []).append(c)
    for hour in by_hour:
        by_hour[hour].sort(key=lambda c: (-c.score, -c.confidence, c.symbol))

    all_hours = sorted(by_hour.keys())
    if not all_hours:
        return []

    open_positions: list[Position] = []
    closed_trades: list[Trade] = []

    hour = all_hours[0]
    last_hour = all_hours[-1] + timedelta(hours=MAX_HOLD_HOURS + 1)
    step = timedelta(hours=1)

    while hour <= last_hour:
        still_open = []
        for pos in open_positions:
            df = price_history.get(pos.symbol)
            bar = None
            if df is not None and len(df):
                match = df[df["timestamp"] == hour]
                if len(match):
                    bar = match.iloc[0]

            age_hours = (hour - pos.entry_time).total_seconds() / 3600.0

            if bar is None:
                if age_hours >= MAX_HOLD_HOURS and df is not None and len(df):
                    prior = df[df["timestamp"] <= hour]
                    if len(prior):
                        last_known = prior.iloc[-1]
                        effective_exit = float(last_known["close"]) * (1.0 - SLIPPAGE_EXIT_PCT)
                        gross_pnl = pos.quantity * (effective_exit - pos.entry_price)
                        exit_fee = (pos.quantity * effective_exit) * EXIT_FEE_RATE
                        net_pnl = gross_pnl - pos.entry_fee - exit_fee
                        closed_trades.append(Trade(
                            symbol=pos.symbol, entry_time=pos.entry_time, exit_time=hour,
                            net_pnl=net_pnl, net_return_pct=(net_pnl / NOTIONAL) * 100.0,
                            exit_reason="TIME_GAP", holding_hours=age_hours,
                        ))
                        continue
                still_open.append(pos)
                continue

            low = float(bar["low"])
            high = float(bar["high"])
            close = float(bar["close"])

            stop_price = pos.entry_price * (1.0 - stop_pct)
            target_price = pos.entry_price * (1.0 + target_pct)

            reason = None
            exit_price = None
            if low <= stop_price:
                reason, exit_price = "STOP", stop_price
            elif high >= target_price:
                reason, exit_price = "TARGET", target_price
            elif age_hours >= MAX_HOLD_HOURS:
                reason, exit_price = "TIME", close

            if reason:
                effective_exit = exit_price * (1.0 - SLIPPAGE_EXIT_PCT)
                gross_pnl = pos.quantity * (effective_exit - pos.entry_price)
                exit_fee = (pos.quantity * effective_exit) * EXIT_FEE_RATE
                net_pnl = gross_pnl - pos.entry_fee - exit_fee
                closed_trades.append(Trade(
                    symbol=pos.symbol, entry_time=pos.entry_time, exit_time=hour,
                    net_pnl=net_pnl, net_return_pct=(net_pnl / NOTIONAL) * 100.0,
                    exit_reason=reason, holding_hours=age_hours,
                ))
            else:
                still_open.append(pos)

        open_positions = still_open

        candidates_this_hour = by_hour.get(hour, [])
        open_keys = {(p.symbol, p.entry_time) for p in open_positions}
        closed_keys = {(t.symbol, t.entry_time) for t in closed_trades}

        for cand in candidates_this_hour:
            if len(open_positions) >= MAX_POSITIONS:
                break
            key = (cand.symbol, cand.entry_time)
            if key in open_keys or key in closed_keys:
                continue

            df = price_history.get(cand.symbol)
            if df is None or not len(df):
                continue
            match = df[df["timestamp"] == cand.entry_time]
            if not len(match):
                continue

            entry_price_raw = float(match.iloc[0]["close"])
            if entry_price_raw <= 0:
                continue

            effective_entry = entry_price_raw * (1.0 + SLIPPAGE_ENTRY_PCT)
            quantity = NOTIONAL / effective_entry
            entry_fee = NOTIONAL * ENTRY_FEE_RATE

            open_positions.append(Position(
                symbol=cand.symbol, entry_time=cand.entry_time,
                entry_price=effective_entry, quantity=quantity, entry_fee=entry_fee,
            ))
            open_keys.add(key)

        hour += step

    return closed_trades


def compute_metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0, "median": None, "mean": None, "win_rate": None, "pf": None, "max_dd": None, "pnl": 0.0}

    returns = [t.net_return_pct for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    trades_sorted = sorted(trades, key=lambda t: t.exit_time)
    equity = CAPITAL
    peak = equity
    max_dd = 0.0
    for t in trades_sorted:
        equity += t.net_pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity - peak) / peak * 100.0)

    return {
        "n": len(trades),
        "median": statistics.median(returns),
        "mean": statistics.mean(returns),
        "win_rate": len(wins) / len(returns) * 100.0,
        "pf": pf,
        "max_dd": max_dd,
        "pnl": sum(t.net_pnl for t in trades),
    }


def print_metrics(label: str, m: dict) -> None:
    if m["n"] == 0:
        print(f"{label:20s} n=0 (sem trades)")
        return
    print(
        f"{label:20s} n={m['n']:4d}  mediana={m['median']:+7.3f}%  "
        f"média={m['mean']:+7.3f}%  win={m['win_rate']:5.1f}%  "
        f"PF={m['pf']:5.2f}  DD={m['max_dd']:7.2f}%  P&L=${m['pnl']:+8.2f}"
    )


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    all_candidates = load_candidates(conn)

    if not all_candidates:
        print("Nenhum sinal de compra encontrado no histórico.")
        return 1

    start = min(c.entry_time for c in all_candidates)
    end = max(c.entry_time for c in all_candidates)
    total_days = (end - start).total_seconds() / 86400.0

    train_end = start + timedelta(days=total_days * 0.75)
    test_start = train_end + timedelta(hours=EMBARGO_HOURS)

    train_candidates = [c for c in all_candidates if c.entry_time < train_end]
    test_candidates = [c for c in all_candidates if c.entry_time >= test_start]

    print("=" * 100)
    print("EXPLORAÇÃO STOP/TARGET COM TREINO/TESTE E EMBARGO")
    print("=" * 100)
    print(f"Período total:  {start} até {end} ({total_days:.1f} dias)")
    print(f"TREINO:         até {train_end}  ({len(train_candidates)} candidatos)")
    print(f"EMBARGO:        {EMBARGO_HOURS}h ({train_end} até {test_start})")
    print(f"TESTE:          a partir de {test_start}  ({len(test_candidates)} candidatos)")
    print()

    symbols = sorted({c.symbol for c in all_candidates})
    fetch_start = start - timedelta(hours=1)
    fetch_end = end + timedelta(hours=MAX_HOLD_HOURS + 2)

    print(f"Baixando histórico de preços na Binance ({len(symbols)} símbolos)...")
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    price_history: dict[str, pd.DataFrame] = {}
    for i, symbol in enumerate(symbols, 1):
        price_history[symbol] = fetch_full_history(exchange, symbol, fetch_start, fetch_end)
        print(f"  [{i}/{len(symbols)}] {symbol:14s} {len(price_history[symbol])} candles")

    print()
    print("-" * 100)
    print(f"GRADE NO TREINO (stop x target, {len(STOP_GRID)}x{len(TARGET_GRID)}={len(STOP_GRID)*len(TARGET_GRID)} combinações)")
    print("-" * 100)

    baseline_train = compute_metrics(simulate(train_candidates, price_history, BASELINE_STOP_PCT, BASELINE_TARGET_PCT))
    print_metrics(f"BASELINE {BASELINE_STOP_PCT:.0%}/{BASELINE_TARGET_PCT:.0%} (treino)", baseline_train)
    print()

    grid_results = []
    for stop_pct in STOP_GRID:
        for target_pct in TARGET_GRID:
            trades = simulate(train_candidates, price_history, stop_pct, target_pct)
            m = compute_metrics(trades)
            grid_results.append((stop_pct, target_pct, m))
            print_metrics(f"{stop_pct:.0%}/{target_pct:.0%} (treino)", m)

    print()
    print("-" * 100)
    print("FILTRO DE CANDIDATOS (N>=30, PF>=1.0, mediana melhor que o baseline no treino)")
    print("-" * 100)

    candidates_to_test = []
    for stop_pct, target_pct, m in grid_results:
        if stop_pct == BASELINE_STOP_PCT and target_pct == BASELINE_TARGET_PCT:
            continue
        if m["n"] < 30 or m["pf"] is None or m["pf"] < 1.0:
            continue
        if baseline_train["median"] is not None and m["median"] is not None and m["median"] <= baseline_train["median"]:
            continue
        candidates_to_test.append((stop_pct, target_pct, m))

    candidates_to_test.sort(key=lambda x: x[2]["median"], reverse=True)
    top_candidates = candidates_to_test[:3]

    if not top_candidates:
        print("Nenhuma combinação passou no filtro (nenhuma bateu a mediana do baseline no treino).")
    else:
        for stop_pct, target_pct, m in top_candidates:
            print(f"Candidato: {stop_pct:.0%}/{target_pct:.0%} -> mediana treino {m['median']:+.3f}%")

    print()
    print("=" * 100)
    print("VEREDITO NO TESTE (dado nunca usado pra escolher nada acima)")
    print("=" * 100)

    baseline_test = compute_metrics(simulate(test_candidates, price_history, BASELINE_STOP_PCT, BASELINE_TARGET_PCT))
    print_metrics(f"BASELINE {BASELINE_STOP_PCT:.0%}/{BASELINE_TARGET_PCT:.0%} (teste)", baseline_test)

    results_rows = [{
        "stop_pct": BASELINE_STOP_PCT, "target_pct": BASELINE_TARGET_PCT, "set": "test",
        **baseline_test, "is_baseline": True,
    }]

    any_beats_baseline = False
    for stop_pct, target_pct, _train_m in top_candidates:
        test_trades = simulate(test_candidates, price_history, stop_pct, target_pct)
        test_m = compute_metrics(test_trades)
        print_metrics(f"{stop_pct:.0%}/{target_pct:.0%} (teste)", test_m)
        results_rows.append({
            "stop_pct": stop_pct, "target_pct": target_pct, "set": "test",
            **test_m, "is_baseline": False,
        })

        if (
            test_m["n"] >= 30
            and test_m["median"] is not None
            and baseline_test["median"] is not None
            and test_m["median"] > baseline_test["median"]
            and test_m["median"] > 0
        ):
            any_beats_baseline = True

    pd.DataFrame(results_rows).to_csv(OUTPUT_CSV, index=False)
    print(f"\nResultados salvos em {OUTPUT_CSV}")

    print()
    print("=" * 100)
    if any_beats_baseline:
        print("Pelo menos um candidato bateu o baseline no TESTE (mediana melhor e positiva).")
        print("Isso é um indício real, mas ainda é 1 backtest - confirmar com mais tempo de forward test")
        print("antes de mudar o parâmetro em produção.")
    else:
        print("NENHUM candidato bateu o baseline de forma robusta no teste fora da amostra.")
        print("Conclusão honesta: não há evidência de que mudar STOP_PCT/TARGET_PCT resolve a")
        print("mediana negativa. O problema provavelmente não está nesses dois parâmetros.")
    print("=" * 100)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
