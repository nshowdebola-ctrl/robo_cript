#!/usr/bin/env python3
"""
CRYPTO RADAR - ANÁLISE: IDADE DE LISTAGEM x DESEMPENHO NO BACKTEST V9

Pergunta: os trades em criptos recém-listadas na Binance tiveram
desempenho pior que em criptos estabelecidas, no backtest histórico
de v9_historical_backtest.py?

Metodologia:
- Para cada símbolo presente em data/v9_historical_backtest_trades.csv,
  busca o candle 1h mais antigo disponível na Binance (proxy de data de
  listagem/início do par spot).
- Classifica idade (em dias, até hoje) em faixas.
- Agrupa os 637 trades já simulados por faixa de idade e compara
  win rate, retorno médio/mediano e profit factor.

Não reabre nenhuma posição nem refaz o backtest - só reclassifica os
trades que já existem em data/v9_historical_backtest_trades.csv.

Uso:
  python3 src/v9_backtest_listing_age_analysis.py
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TRADES_CSV = ROOT / "data" / "v9_historical_backtest_trades.csv"
OUTPUT_CSV = ROOT / "data" / "v9_backtest_listing_age.csv"

# Corte antigo o suficiente para pegar o primeiro candle real de
# qualquer par (Binance spot não existia antes de 2017).
EARLIEST_POSSIBLE = datetime(2017, 1, 1, tzinfo=timezone.utc)


def first_candle_date(exchange: ccxt.binance, symbol: str) -> datetime | None:
    market = f"{symbol}/USDT"
    try:
        candles = exchange.fetch_ohlcv(
            market, timeframe="1d",
            since=int(EARLIEST_POSSIBLE.timestamp() * 1000),
            limit=1,
        )
    except Exception as exc:
        print(f"  AVISO {market}: {exc}")
        return None

    if not candles:
        return None
    return datetime.fromtimestamp(candles[0][0] / 1000, tz=timezone.utc)


def age_bucket(days: float) -> str:
    if days < 90:
        return "< 90 dias (recém-listada)"
    if days < 365:
        return "90-365 dias (moderada)"
    return ">= 365 dias (estabelecida)"


def main() -> int:
    trades = pd.read_csv(TRADES_CSV)
    trades["base_symbol"] = trades["symbol"].str.replace("/USDT", "", regex=False)

    symbols = sorted(trades["base_symbol"].unique())
    print(f"Símbolos nos trades do backtest: {len(symbols)}")
    print("Consultando data do primeiro candle na Binance para cada um...")

    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})

    now = datetime.now(timezone.utc)
    ages = {}
    for symbol in symbols:
        first_dt = first_candle_date(exchange, symbol)
        if first_dt is None:
            continue
        age_days = (now - first_dt).total_seconds() / 86400.0
        ages[symbol] = age_days
        print(f"  {symbol:10s} listado em {first_dt.date()}  ({age_days:6.0f} dias atrás)  -> {age_bucket(age_days)}")

    trades["listing_age_days"] = trades["base_symbol"].map(ages)
    trades["age_bucket"] = trades["listing_age_days"].apply(
        lambda d: age_bucket(d) if pd.notna(d) else "desconhecida"
    )

    trades.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSalvo em {OUTPUT_CSV}")

    print()
    print("=" * 100)
    print("DESEMPENHO POR FAIXA DE IDADE DE LISTAGEM")
    print("=" * 100)

    order = [
        "< 90 dias (recém-listada)",
        "90-365 dias (moderada)",
        ">= 365 dias (estabelecida)",
        "desconhecida",
    ]

    for bucket in order:
        subset = trades[trades["age_bucket"] == bucket]
        if subset.empty:
            continue

        returns = subset["net_return_pct"]
        wins = returns[returns > 0]
        losses = returns[returns <= 0]
        win_rate = len(wins) / len(returns) * 100.0
        gross_win = wins.sum()
        gross_loss = abs(losses.sum())
        pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        n_symbols = subset["base_symbol"].nunique()

        print(f"\n--- {bucket} ---")
        print(f"  Trades: {len(subset)}   Símbolos: {n_symbols}")
        print(f"  Win rate:        {win_rate:.1f}%")
        print(f"  Retorno médio:   {returns.mean():+.3f}%")
        print(f"  Retorno mediano: {returns.median():+.3f}%")
        print(f"  Profit factor:   {pf:.2f}")
        print(f"  P&L total:       ${subset['net_pnl'].sum():+.2f}")

    print()
    print("=" * 100)


if __name__ == "__main__":
    raise SystemExit(main())
