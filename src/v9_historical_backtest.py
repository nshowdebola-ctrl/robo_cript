#!/usr/bin/env python3
"""
CRYPTO RADAR - BACKTEST HISTÓRICO DAS REGRAS DA V9

Objetivo: responder "se a V9.17/V9.18 estivessem rodando desde que o
scanner começou a coletar dado, o que teria acontecido?" - usando as
MESMAS regras já em produção (importadas de paper_trading_v9_17.py,
não reimplementadas), contra o histórico real já coletado em
scanner_v3_results (~6 semanas, 108 símbolos).

Isto NÃO é otimização de parâmetros. Nenhum parâmetro é ajustado aqui -
STOP_PCT, TARGET_PCT, MAX_HOLD_HOURS, NOTIONAL, MAX_POSITIONS, fees e
slippage vêm todos de paper_trading_v9_17.py sem alteração.

Metodologia:
- Preço de entrada e movimento pós-entrada vêm de candles 1h reais
  buscados na Binance (não do valor "price" já salvo no banco, para
  usar máxima/mínima de cada hora e detectar STOP/TARGET intra-hora,
  não só o fechamento).
- Processa os sinais em ordem cronológica, respeitando MAX_POSITIONS
  (não abre mais posições do que vagas livres, igual à V9.17 real).
- Sinais no mesmo horário competem por vaga na mesma ordem que o
  adaptador real usa: score DESC, confidence DESC, symbol ASC.
- Se STOP e TARGET forem ambos atingidos na mesma vela (whipsaw),
  assume STOP primeiro (convenção conservadora, evita otimismo
  artificial).
- Posições ainda abertas ao final do período NÃO entram nas
  estatísticas de P&L (não inventamos um preço de saída para elas).

Uso:
  python3 src/v9_historical_backtest.py
"""

from __future__ import annotations

import sqlite3
import statistics
import time
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
    STOP_PCT,
    TARGET_PCT,
)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "crypto_radar.db"
OUTPUT_CSV = ROOT / "data" / "v9_historical_backtest_trades.csv"

TIMEFRAME = "1h"


@dataclass
class Candidate:
    entry_time: datetime
    symbol: str
    score: float
    confidence: float


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
    entry_price: float
    exit_price: float
    net_pnl: float
    net_return_pct: float
    exit_reason: str
    holding_hours: float


def load_candidates(conn: sqlite3.Connection) -> list[Candidate]:
    rows = conn.execute(
        """
        SELECT timestamp, symbol, score, confidence
        FROM scanner_v3_results
        WHERE timeframe = ?
          AND signal IN ('COMPRA', 'COMPRA FORTE')
        ORDER BY timestamp ASC
        """,
        (TIMEFRAME,),
    ).fetchall()

    out = []
    for ts, symbol, score, confidence in rows:
        out.append(Candidate(
            entry_time=datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
            if datetime.fromisoformat(ts).tzinfo is None
            else datetime.fromisoformat(ts),
            symbol=symbol,
            score=float(score or 0),
            confidence=float(confidence or 0),
        ))
    return out


def fetch_full_history(exchange: ccxt.binance, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Busca todo o histórico 1h de um símbolo no intervalo, paginando."""
    all_candles = []
    since = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    while since < end_ms:
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, since=since, limit=1000)
        except Exception as exc:
            print(f"  AVISO {symbol}: falha ao buscar candles ({exc})")
            break

        if not batch:
            break

        all_candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= since:
            break
        since = last_ts + 1

        if len(batch) < 1000:
            break

    if not all_candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


def simulate(
    candidates: list[Candidate],
    price_history: dict[str, pd.DataFrame],
) -> tuple[list[Trade], list[Position]]:

    # Agrupa candidatos por horário de entrada, na mesma ordem de
    # prioridade que scanner_v3_to_v9.py grava no CSV real.
    by_hour: dict[datetime, list[Candidate]] = {}
    for c in candidates:
        by_hour.setdefault(c.entry_time, []).append(c)
    for hour in by_hour:
        by_hour[hour].sort(key=lambda c: (-c.score, -c.confidence, c.symbol))

    all_hours = sorted(by_hour.keys())
    if not all_hours:
        return [], []

    open_positions: list[Position] = []
    closed_trades: list[Trade] = []

    # Também precisamos "visitar" horas em que não há candidato novo,
    # só para monitorar posições abertas (STOP/TARGET/TIME).
    hour = all_hours[0]
    last_hour = all_hours[-1] + timedelta(hours=MAX_HOLD_HOURS + 1)
    step = timedelta(hours=1)

    while hour <= last_hour:
        # 1) Monitorar posições abertas nesta hora.
        still_open = []
        for pos in open_positions:
            df = price_history.get(pos.symbol)
            bar = None
            if df is not None and len(df):
                match = df[df["timestamp"] == hour]
                if len(match):
                    bar = match.iloc[0]

            if bar is None:
                still_open.append(pos)
                continue

            age_hours = (hour - pos.entry_time).total_seconds() / 3600.0
            low = float(bar["low"])
            high = float(bar["high"])
            close = float(bar["close"])

            stop_price = pos.entry_price * (1.0 - STOP_PCT)
            target_price = pos.entry_price * (1.0 + TARGET_PCT)

            reason = None
            exit_price = None

            if low <= stop_price:
                reason = "STOP"
                exit_price = stop_price
            elif high >= target_price:
                reason = "TARGET"
                exit_price = target_price
            elif age_hours >= MAX_HOLD_HOURS:
                reason = "TIME"
                exit_price = close

            if reason:
                effective_exit = exit_price * (1.0 - SLIPPAGE_EXIT_PCT)
                gross_pnl = pos.quantity * (effective_exit - pos.entry_price)
                exit_notional = pos.quantity * effective_exit
                exit_fee = exit_notional * EXIT_FEE_RATE
                net_pnl = gross_pnl - pos.entry_fee - exit_fee
                notional = NOTIONAL
                net_return_pct = (net_pnl / notional) * 100.0

                closed_trades.append(Trade(
                    symbol=pos.symbol,
                    entry_time=pos.entry_time,
                    exit_time=hour,
                    entry_price=pos.entry_price,
                    exit_price=effective_exit,
                    net_pnl=net_pnl,
                    net_return_pct=net_return_pct,
                    exit_reason=reason,
                    holding_hours=age_hours,
                ))
            else:
                still_open.append(pos)

        open_positions = still_open

        # 2) Abrir sinais novos desta hora, respeitando vagas livres.
        candidates_this_hour = by_hour.get(hour, [])
        open_symbols_times = {(p.symbol, p.entry_time) for p in open_positions}
        closed_symbols_times = {(t.symbol, t.entry_time) for t in closed_trades}

        for cand in candidates_this_hour:
            if len(open_positions) >= MAX_POSITIONS:
                break

            key = (cand.symbol, cand.entry_time)
            if key in open_symbols_times or key in closed_symbols_times:
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
                symbol=cand.symbol,
                entry_time=cand.entry_time,
                entry_price=effective_entry,
                quantity=quantity,
                entry_fee=entry_fee,
            ))
            open_symbols_times.add(key)

        hour += step

    return closed_trades, open_positions


def report(trades: list[Trade], still_open: list[Position]) -> None:
    print("=" * 100)
    print("RESULTADO DO BACKTEST HISTÓRICO - REGRAS REAIS DA V9.17/V9.18")
    print("=" * 100)
    print(f"Trades fechados:        {len(trades)}")
    print(f"Posições ainda abertas ao fim do período (excluídas do P&L): {len(still_open)}")

    if not trades:
        print("Sem trades fechados suficientes para estatística.")
        return

    returns = [t.net_return_pct for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    total_pnl = sum(t.net_pnl for t in trades)
    mean_r = statistics.mean(returns)
    median_r = statistics.median(returns)
    win_rate = len(wins) / len(returns) * 100.0

    gross_win = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r <= 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # Equity curve simples: capital fixo, soma de P&L realizado ao longo do tempo.
    trades_sorted = sorted(trades, key=lambda t: t.exit_time)
    equity = CAPITAL
    peak = equity
    max_dd = 0.0
    for t in trades_sorted:
        equity += t.net_pnl
        peak = max(peak, equity)
        dd = (equity - peak) / peak * 100.0
        max_dd = min(max_dd, dd)

    print(f"P&L líquido total:      ${total_pnl:,.2f}  (capital de referência ${CAPITAL:,.2f})")
    print(f"Retorno médio/trade:    {mean_r:+.3f}%")
    print(f"Retorno mediano/trade:  {median_r:+.3f}%")
    print(f"Win rate:               {win_rate:.1f}%")
    print(f"Profit factor:          {profit_factor:.2f}")
    print(f"Max drawdown (equity):  {max_dd:.2f}%")
    print(f"Melhor trade:           {max(returns):+.2f}%")
    print(f"Pior trade:             {min(returns):+.2f}%")

    # Consistência temporal: primeira metade vs segunda metade.
    mid = len(trades_sorted) // 2
    first_half = trades_sorted[:mid]
    second_half = trades_sorted[mid:]
    fh_pnl = sum(t.net_pnl for t in first_half)
    sh_pnl = sum(t.net_pnl for t in second_half)
    print()
    print(f"Primeira metade (n={len(first_half)}): P&L ${fh_pnl:,.2f}")
    print(f"Segunda metade  (n={len(second_half)}): P&L ${sh_pnl:,.2f}")

    # Sensibilidade a custo: e se fee+slippage fossem o dobro?
    extra_cost_pct = (ENTRY_FEE_RATE + EXIT_FEE_RATE + SLIPPAGE_ENTRY_PCT + SLIPPAGE_EXIT_PCT) * 100.0
    stressed_pnl = sum(t.net_pnl - (extra_cost_pct / 100.0) * NOTIONAL for t in trades)
    print(f"P&L com custo 2x (fee+slippage dobrados): ${stressed_pnl:,.2f}")

    print()
    print("-" * 100)
    print("VEREDITO (mesmos critérios já usados no projeto para gates anteriores)")
    print("-" * 100)
    checks = {
        "N >= 30 trades": len(trades) >= 30,
        "Mediana positiva": median_r > 0,
        "Profit factor >= 1.20": profit_factor >= 1.20,
        "Drawdown > -30%": max_dd > -30.0,
        "Primeira e segunda metade ambas positivas": fh_pnl > 0 and sh_pnl > 0,
        "Sobrevive a custo 2x": stressed_pnl > 0,
    }
    for label, passed in checks.items():
        print(f"  [{'OK' if passed else 'FALHOU'}] {label}")

    approved = all(checks.values())
    print()
    print("APROVADA (indício preliminar de edge real)" if approved else "NÃO APROVADA (ainda sem evidência suficiente de edge real)")
    print("=" * 100)
    print("IMPORTANTE: isto é um backtest sobre dado histórico, não um forward test.")
    print("Não substitui o acompanhamento real da V9 rodando ao vivo - é um indício")
    print("mais rápido para decidir se vale continuar investindo tempo nisso.")


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    candidates = load_candidates(conn)

    if not candidates:
        print("Nenhum sinal de compra encontrado no histórico.")
        return 1

    symbols = sorted({c.symbol for c in candidates})
    start = min(c.entry_time for c in candidates) - timedelta(hours=1)
    end = max(c.entry_time for c in candidates) + timedelta(hours=MAX_HOLD_HOURS + 2)

    print(f"Símbolos com sinal de compra no histórico: {len(symbols)}")
    print(f"Sinais candidatos totais: {len(candidates)}")
    print(f"Período: {start} até {end}")
    print("Baixando histórico de preços na Binance (1x por símbolo, paginado)...")

    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})

    price_history: dict[str, pd.DataFrame] = {}
    for i, symbol in enumerate(symbols, 1):
        df = fetch_full_history(exchange, symbol, start, end)
        price_history[symbol] = df
        print(f"  [{i}/{len(symbols)}] {symbol:14s} {len(df)} candles")

    print()
    print("Simulando...")
    trades, still_open = simulate(candidates, price_history)

    if trades:
        pd.DataFrame([{
            "symbol": t.symbol,
            "entry_time": t.entry_time.isoformat(),
            "exit_time": t.exit_time.isoformat(),
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "net_pnl": t.net_pnl,
            "net_return_pct": t.net_return_pct,
            "exit_reason": t.exit_reason,
            "holding_hours": t.holding_hours,
        } for t in trades]).to_csv(OUTPUT_CSV, index=False)
        print(f"Trades salvos em {OUTPUT_CSV}")

    print()
    report(trades, still_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
