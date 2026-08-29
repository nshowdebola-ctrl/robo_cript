#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.16
Scanner -> forward_signals.csv

Produz sinais forward a partir de dados OHLCV disponíveis via CCXT/Binance.
PAPER ONLY. Nenhuma ordem real.

Regras:
- somente candles fechados;
- nenhum uso do CSV legado V8;
- somente sinais novos são gravados;
- sem sinal válido, não cria arquivo financeiro/trade;
- o arquivo de sinais é um contrato de entrada para o V9.15.

Uso:
    python3 src/paper_trading_v9_16.py
"""

from __future__ import annotations

import csv
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import ccxt
except ImportError:
    print("ERRO: ccxt não está instalado no ambiente atual.")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "forward_signals.csv"

TIMEFRAME = "1h"
LIMIT = 120
MIN_QUOTE_VOLUME = 1_000_000.0
MAX_SYMBOLS = 50

FIELDS = [
    "signal_id",
    "scenario",
    "symbol",
    "entry_time",
    "entry_price",
    "timeframe",
    "score",
    "confidence",
    "signal",
]

def finite(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def rsi(closes, period=14):
    if len(closes) <= period:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - (100.0 / (1.0 + rs))

def ema(values, period):
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e

def closed_candles(exchange, symbol):
    candles = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
    if len(candles) < 60:
        return []
    # O último candle pode estar aberto. O retiramos sem tentar adivinhar
    # o fechamento.
    return candles[:-1]

def build_signal(symbol, candles):
    closes = [float(x[4]) for x in candles]
    volumes = [float(x[5]) for x in candles]

    price = closes[-1]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    rv = rsi(closes, 14)

    if e20 is None or e50 is None or rv is None:
        return None

    vol_base = sum(volumes[-21:-1]) / 20.0
    relvol = volumes[-1] / vol_base if vol_base > 0 else 0.0
    momentum4h = (price / closes[-5] - 1.0) * 100.0

    score = 0
    if 50 <= rv <= 70:
        score += 25
    elif 45 <= rv < 50:
        score += 15
    elif 70 < rv <= 75:
        score += 10

    if price > e20:
        score += 15
    if e20 > e50:
        score += 20

    if momentum4h > 0:
        score += 15
    if momentum4h >= 0.5:
        score += 5

    if relvol >= 1.20:
        score += 20
    elif relvol >= 1.00:
        score += 10

    # Gate conservador: tendência + momentum + volume.
    if score < 70:
        return None
    if price <= e20 or e20 <= e50 or momentum4h <= 0 or relvol < 1.0:
        return None

    confidence = min(100.0, float(score))
    entry_time = datetime.fromtimestamp(
        candles[-1][0] / 1000.0, tz=timezone.utc
    ).isoformat()

    return {
        "scenario": "V9.16_FORWARD",
        "symbol": symbol,
        "entry_time": entry_time,
        "entry_price": f"{price:.12f}",
        "timeframe": TIMEFRAME,
        "score": f"{score:.2f}",
        "confidence": f"{confidence:.2f}",
        "signal": "LONG",
    }

def main():
    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.16 -- SCANNER FORWARD")
    print("=" * 100)
    print(f"Timeframe: {TIMEFRAME}")
    print(f"Limite de candles: {LIMIT}")
    print(f"Volume mínimo 24h: ${MIN_QUOTE_VOLUME:,.0f}")
    print(f"Máximo de mercados: {MAX_SYMBOLS}")
    print(f"Saída: {OUT}")
    print("Modo: PAPER ONLY")
    print("Ordens reais: NÃO")
    print("CSV legado V8: NÃO UTILIZADO")
    print("-" * 100)

    DATA.mkdir(parents=True, exist_ok=True)

    exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })

    print("Carregando mercados Binance...")
    markets = exchange.load_markets()

    symbols = []
    for s, m in markets.items():
        if not m.get("active", True):
            continue
        if m.get("spot") is not True:
            continue
        if m.get("quote") != "USDT":
            continue
        symbols.append(s)

    print(f"Mercados spot USDT encontrados: {len(symbols)}")

    candidates = []
    print("Obtendo tickers...")
    for i in range(0, len(symbols), 20):
        batch = symbols[i:i+20]
        try:
            tickers = exchange.fetch_tickers(batch)
        except Exception:
            # Evita abortar todo o ciclo por um lote problemático.
            continue

        for symbol, ticker in tickers.items():
            qv = finite(ticker.get("quoteVolume"))
            if qv is not None and qv >= MIN_QUOTE_VOLUME:
                candidates.append((symbol, qv))

    candidates.sort(key=lambda x: x[1], reverse=True)
    candidates = candidates[:MAX_SYMBOLS]

    print(f"Mercados candidatos: {len(candidates)}")

    signals = []
    for symbol, _ in candidates:
        try:
            candles = closed_candles(exchange, symbol)
            signal = build_signal(symbol, candles)
            if signal:
                signals.append(signal)
        except Exception as exc:
            print(f"  AVISO {symbol}: {exc}")

    # Evita duplicar o mesmo sinal se o arquivo já existir.
    existing = []
    if OUT.exists():
        try:
            with OUT.open("r", newline="", encoding="utf-8-sig") as f:
                existing = list(csv.DictReader(f))
        except Exception:
            existing = []

    existing_keys = {
        (r.get("symbol", "").strip().upper(), r.get("entry_time", "").strip())
        for r in existing
    }

    fresh = [
        s for s in signals
        if (s["symbol"].upper(), s["entry_time"]) not in existing_keys
    ]

    if fresh:
        write_header = not OUT.exists() or OUT.stat().st_size == 0
        with OUT.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if write_header:
                w.writeheader()
            for i, s in enumerate(fresh, 1):
                row = dict(s)
                row["signal_id"] = (
                    datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                    + f"_{i:03d}"
                )
                w.writerow(row)

    print("-" * 100)
    print(f"Sinais encontrados no ciclo: {len(signals)}")
    print(f"Sinais novos gravados:       {len(fresh)}")
    print(f"Arquivo: {OUT}")

    if not fresh:
        print("Nenhum sinal novo. Nenhum trade financeiro foi inventado.")

    print("=" * 100)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
