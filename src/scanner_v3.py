#!/usr/bin/env python3

"""
CRYPTO RADAR - SCANNER V3

V3 inclui:
- análise em 1h
- somente candles fechados
- RSI
- tendência 1h
- tendência 4h
- momentum 4h
- volume relativo
- ATR percentual
- score 0-100
- classificação
- sinal
- confiança
- flags de risco
- ranking detalhado
- TOP 10
- sinais
- persistência em SQLite
- retry de OHLCV
- timeout de rede
- proteção contra problemas de banco

Execute:

    .venv/bin/python src/scanner_v3.py
"""

from __future__ import annotations

import sqlite3
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ccxt
import numpy as np
import pandas as pd


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "crypto_radar.db"

TIMEFRAME = "1h"
# 240 candles de 1h (10 dias) garantem ~55-60 candles de 4h após o
# resample - abaixo disso, trend_points_4h() nunca teria dado
# fechado suficiente pra calcular EMA50 de 4h e sempre pontuaria 0.
CANDLES = 240

TOP_MARKETS = 50
MIN_VOLUME_USDT = 1_000_000

# Idade mínima de listagem na Binance para um símbolo ser analisado.
# Justificado por dado real: no backtest histórico das regras da V9
# (src/v9_backtest_listing_age_analysis.py), símbolos com < 90 dias de
# listagem tiveram profit factor 0.86 (deficitário sozinho) contra 1.22
# dos símbolos com >= 365 dias - gradiente consistente em toda métrica.
MIN_LISTING_AGE_DAYS = 90

NETWORK_TIMEOUT_MS = 15_000
OHLCV_RETRIES = 3

DB_TIMEOUT = 30
DB_RETRIES = 8

TOP_10 = 10


# ============================================================
# BINANCE
# ============================================================

def create_exchange() -> ccxt.binance:
    exchange = ccxt.binance({
        "enableRateLimit": True,
        "timeout": NETWORK_TIMEOUT_MS,
        "options": {
            "defaultType": "spot",
        },
    })

    return exchange


# ============================================================
# BANCO
# ============================================================

def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(
        DB_PATH,
        timeout=DB_TIMEOUT,
    )

    db.execute("PRAGMA busy_timeout = 30000")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")

    return db


def init_database() -> None:
    """Garante que a tabela V3 tenha o schema compatível com o scanner.

    A tabela pode ter sido criada por versões anteriores do projeto.
    Por isso, além de CREATE TABLE IF NOT EXISTS, adicionamos colunas
    ausentes sem apagar os dados históricos.
    """
    db = connect_db()
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS scanner_v3_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                price REAL NOT NULL,
                rsi REAL,
                ema20 REAL,
                ema50 REAL,
                price_4h REAL NOT NULL DEFAULT 0,
                ema20_4h REAL NOT NULL DEFAULT 0,
                ema50_4h REAL NOT NULL DEFAULT 0,
                momentum_4h REAL NOT NULL DEFAULT 0,
                relative_volume REAL NOT NULL DEFAULT 0,
                atr REAL NOT NULL DEFAULT 0,
                atr_percent REAL NOT NULL DEFAULT 0,
                volatility REAL NOT NULL DEFAULT 0,
                rsi_points INTEGER NOT NULL DEFAULT 0,
                trend_1h_points INTEGER NOT NULL DEFAULT 0,
                trend_4h_points INTEGER NOT NULL DEFAULT 0,
                momentum_points INTEGER NOT NULL DEFAULT 0,
                volume_points INTEGER NOT NULL DEFAULT 0,
                volatility_points INTEGER NOT NULL DEFAULT 0,
                score INTEGER NOT NULL DEFAULT 0,
                classification TEXT NOT NULL DEFAULT 'NEUTRO',
                signal TEXT NOT NULL DEFAULT 'SEM SINAL',
                confidence INTEGER NOT NULL DEFAULT 0,
                risk_flags TEXT,
                risk_count INTEGER NOT NULL DEFAULT 0,
                trend_1h REAL DEFAULT 0,
                trend_4h REAL DEFAULT 0,
                momentum REAL DEFAULT 0,
                volume REAL DEFAULT 0,
                volume_relative REAL DEFAULT 0,
                risks TEXT DEFAULT ''
            )
            """
        )

        existing = {row[1] for row in db.execute("PRAGMA table_info(scanner_v3_results)")}

        additions = {
            "run_at": "TEXT",
            "price_4h": "REAL NOT NULL DEFAULT 0",
            "ema20_4h": "REAL NOT NULL DEFAULT 0",
            "ema50_4h": "REAL NOT NULL DEFAULT 0",
            "atr": "REAL NOT NULL DEFAULT 0",
            "volatility": "REAL NOT NULL DEFAULT 0",
            "volatility_points": "INTEGER NOT NULL DEFAULT 0",
            "risk_flags": "TEXT",
            "risk_count": "INTEGER NOT NULL DEFAULT 0",
            "trend_1h": "REAL DEFAULT 0",
            "trend_4h": "REAL DEFAULT 0",
            "momentum": "REAL DEFAULT 0",
            "volume": "REAL DEFAULT 0",
            "volume_relative": "REAL DEFAULT 0",
            "risks": "TEXT DEFAULT ''",
        }

        for column, definition in additions.items():
            if column not in existing:
                db.execute(f"ALTER TABLE scanner_v3_results ADD COLUMN {column} {definition}")

        db.commit()
    finally:
        db.close()

def save_results(results: list[dict[str, Any]], run_at: str) -> int:
    if not results:
        return 0

    # O banco atual possui colunas extras e várias delas são NOT NULL.
    # Gravamos explicitamente todas as colunas relevantes para evitar
    # incompatibilidade entre versões do scanner e do schema.
    #
    # run_at identifica esta execução do scanner (horário real em que
    # rodou), diferente de "timestamp" (horário do candle analisado).
    # Sem essa distinção, duas execuções dentro da mesma hora podem
    # analisar o mesmo candle ainda não fechado na próxima vela e o
    # adaptador V9.20 não consegue distinguir "última rodada" de
    # "rodada anterior que caiu no mesmo candle".
    columns = [
        "run_at", "timestamp", "symbol", "timeframe", "price",
        "rsi", "ema20", "ema50",
        "price_4h", "ema20_4h", "ema50_4h",
        "momentum_4h", "relative_volume",
        "atr", "atr_percent", "volatility",
        "rsi_points", "trend_1h_points", "trend_4h_points",
        "momentum_points", "volume_points", "volatility_points",
        "score", "classification", "signal", "confidence",
        "risk_flags", "risk_count",
        "trend_1h", "trend_4h", "momentum", "volume",
        "volume_relative", "risks"
    ]
    placeholders = ", ".join("?" for _ in columns)

    rows = []
    for r in results:
        risks_text = ",".join(r.get("risks", []))
        rows.append((
            run_at, r["timestamp"], r["symbol"], TIMEFRAME, r["price"],
            r["rsi"], r["ema20"], r["ema50"],
            r["price_4h"], r["ema20_4h"], r["ema50_4h"],
            r["momentum_4h"], r["relative_volume"],
            r["atr"], r["atr_percent"], r["volatility"],
            r["rsi_points"], r["trend_1h_points"], r["trend_4h_points"],
            r["momentum_points"], r["volume_points"], r["volatility_points"],
            r["score"], r["classification"], r["signal"], r["confidence"],
            risks_text, len(r.get("risks", [])),
            r["trend_1h"], r["trend_4h"], r["momentum_4h"],
            r["relative_volume"], r["relative_volume"], risks_text
        ))

    for attempt in range(1, DB_RETRIES + 1):
        db = None
        try:
            db = connect_db()
            db.executemany(
                f"INSERT INTO scanner_v3_results ({', '.join(columns)}) VALUES ({placeholders})",
                rows,
            )
            db.commit()
            return len(rows)
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            if attempt >= DB_RETRIES:
                raise
            time.sleep(0.5 + attempt * 0.4)
        finally:
            if db is not None:
                db.close()

    return 0


# ============================================================
# INDICADORES
# ============================================================

def calculate_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    if avg_loss.iloc[-1] == 0:
        return 100.0

    rs = avg_gain.iloc[-1] / avg_loss.iloc[-1]

    return float(100 - (100 / (1 + rs)))


def calculate_atr_raw(df: pd.DataFrame, period: int = 14) -> float:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    previous_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - previous_close).abs()
    tr3 = (low - previous_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(period).mean().iloc[-1]
    return 0.0 if pd.isna(atr) else float(atr)


def calculate_atr(
    df: pd.DataFrame,
    period: int = 14,
) -> float:
    atr = calculate_atr_raw(df, period)
    price = float(df["close"].iloc[-1])
    if price <= 0:
        return 0.0
    return float((atr / price) * 100)


def calculate_relative_volume(
    df: pd.DataFrame,
    period: int = 20,
) -> float:

    current_volume = float(df["volume"].iloc[-1])

    average_volume = (
        df["volume"]
        .rolling(period)
        .mean()
        .iloc[-1]
    )

    if average_volume <= 0 or math.isnan(average_volume):
        return 0.0

    return current_volume / average_volume


def calculate_momentum_4h(df: pd.DataFrame) -> float:
    if len(df) < 5:
        return 0.0

    current = float(df["close"].iloc[-1])
    previous = float(df["close"].iloc[-5])

    if previous <= 0:
        return 0.0

    return ((current / previous) - 1) * 100


# ============================================================
# TREND
# ============================================================

def trend_points_1h(
    price: float,
    ema20: float,
    ema50: float,
) -> int:

    if price > ema20 > ema50:
        return 25

    if price > ema20 and ema20 <= ema50:
        return 15

    if price > ema50:
        return 15

    return 0


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()

    data = data.set_index("timestamp")

    result = data.resample("4h").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )

    result = result.dropna().reset_index()

    return result


def trend_points_4h(df: pd.DataFrame) -> int:
    if len(df) < 50:
        return 0

    close = df["close"]

    ema20 = close.ewm(
        span=20,
        adjust=False,
    ).mean()

    ema50 = close.ewm(
        span=50,
        adjust=False,
    ).mean()

    price = float(close.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])

    if price > e20 > e50:
        return 20

    if price > e20:
        return 14

    if price > e50:
        return 7

    return 0


# ============================================================
# SCORE
# ============================================================

def rsi_points(rsi: float) -> int:
    """
    Máximo: 20 pontos.

    Evita premiar excessivamente RSI extremamente sobrecomprado.
    """

    if rsi >= 50 and rsi < 70:
        return 20

    if rsi >= 45 and rsi < 50:
        return 19

    if rsi >= 40 and rsi < 45:
        return 15

    if rsi >= 30 and rsi < 40:
        return 11

    if rsi >= 70 and rsi < 75:
        return 15

    if rsi >= 75:
        return 3

    if rsi >= 20:
        return 7

    return 2


def momentum_points(momentum: float) -> int:
    if momentum >= 2.0:
        return 15

    if momentum >= 1.0:
        return 13

    if momentum >= 0.5:
        return 10

    if momentum >= 0.0:
        return 7

    if momentum >= -1.0:
        return 3

    return 0


def volume_points(relative_volume: float) -> int:
    if relative_volume >= 2.0:
        return 15

    if relative_volume >= 1.5:
        return 12

    if relative_volume >= 1.0:
        return 9

    if relative_volume >= 0.5:
        return 4

    return 0


def volatility_points(atr_percent: float) -> int:
    # Quanto menor o ATR, maior a pontuação de estabilidade.
    if atr_percent <= 1.0:
        return 10
    if atr_percent <= 2.0:
        return 8
    if atr_percent <= 3.0:
        return 5
    if atr_percent <= 5.0:
        return 2
    return 0


# ============================================================
# CLASSIFICAÇÃO
# ============================================================

def classify(score: int) -> str:

    if score >= 90:
        return "EXCEPCIONAL"

    if score >= 75:
        return "MUITO FORTE"

    if score >= 60:
        return "FORTE"

    if score >= 45:
        return "MODERADO"

    if score >= 35:
        return "NEUTRO"

    if score >= 20:
        return "FRACO"

    return "MUITO FRACO"


def signal(score: int) -> str:

    if score >= 80:
        return "COMPRA FORTE"

    if score >= 65:
        return "COMPRA"

    return "SEM SINAL"


# ============================================================
# RISCOS
# ============================================================

def risk_flags(
    rsi: float,
    momentum: float,
    atr_percent: float,
    relative_volume: float,
) -> list[str]:

    flags: list[str] = []

    if rsi >= 75:
        flags.append("RSI_SOBRECOMPRADO")

    if momentum < 0:
        flags.append("MOMENTUM_NEGATIVO")

    if atr_percent >= 5:
        flags.append("VOLATILIDADE_ALTA")

    if relative_volume < 0.5:
        flags.append("VOLUME_BAIXO")

    return flags


# ============================================================
# CONFIANÇA
# ============================================================

def confidence(
    score: int,
    trend_1h: int,
    trend_4h: int,
    momentum: float,
    relative_volume: float,
    risks: list[str],
) -> int:

    """
    Confiança baseada na combinação dos componentes.

    O valor é limitado entre 0 e 100.
    """

    value = 0

    # força do score
    if score >= 90:
        value += 35
    elif score >= 80:
        value += 30
    elif score >= 70:
        value += 25
    elif score >= 60:
        value += 18
    elif score >= 50:
        value += 12
    elif score >= 40:
        value += 6

    # tendência 1h
    if trend_1h >= 25:
        value += 20
    elif trend_1h >= 15:
        value += 12

    # tendência 4h
    if trend_4h >= 20:
        value += 20
    elif trend_4h >= 14:
        value += 14
    elif trend_4h > 0:
        value += 7

    # momentum
    if momentum >= 2:
        value += 10
    elif momentum >= 1:
        value += 8
    elif momentum >= 0.5:
        value += 5
    elif momentum >= 0:
        value += 2

    # volume
    if relative_volume >= 2:
        value += 15
    elif relative_volume >= 1.5:
        value += 12
    elif relative_volume >= 1:
        value += 8
    elif relative_volume >= 0.5:
        value += 4

    # penalizações
    if "RSI_SOBRECOMPRADO" in risks:
        value -= 7

    if "MOMENTUM_NEGATIVO" in risks:
        value -= 10

    if "VOLATILIDADE_ALTA" in risks:
        value -= 8

    if "VOLUME_BAIXO" in risks:
        value -= 8

    return max(0, min(100, int(value)))


# ============================================================
# OHLCV
# ============================================================

def fetch_ohlcv(
    exchange: ccxt.binance,
    symbol: str,
) -> list[list[float]]:

    last_error: Exception | None = None

    for attempt in range(1, OHLCV_RETRIES + 1):

        try:
            print(
                f"  Buscando OHLCV "
                f"(tentativa {attempt}/{OHLCV_RETRIES})..."
            )

            candles = exchange.fetch_ohlcv(
                symbol,
                timeframe=TIMEFRAME,
                limit=CANDLES + 2,
            )

            if not candles:
                raise RuntimeError(
                    "Binance não retornou candles."
                )

            # Remove candle atual ainda aberto.
            now_ms = exchange.milliseconds()

            timeframe_ms = exchange.parse_timeframe(
                TIMEFRAME
            ) * 1000

            closed = [
                candle
                for candle in candles
                if candle[0] + timeframe_ms <= now_ms
            ]

            closed = closed[-CANDLES:]

            if len(closed) < CANDLES:
                raise RuntimeError(
                    f"Candles fechados insuficientes: "
                    f"{len(closed)}/{CANDLES}"
                )

            print(
                f"  ✓ {len(closed)} candles fechados"
            )

            return closed

        except Exception as exc:
            last_error = exc

            if attempt < OHLCV_RETRIES:
                time.sleep(attempt)

    raise RuntimeError(
        f"Falha ao obter OHLCV de {symbol}: "
        f"{last_error}"
    )


# ============================================================
# DATAFRAME
# ============================================================

def candles_to_dataframe(
    candles: list[list[float]],
) -> pd.DataFrame:

    df = pd.DataFrame(
        candles,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        unit="ms",
        utc=True,
    )

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        )

    df = df.dropna().reset_index(drop=True)

    return df


# ============================================================
# ANÁLISE
# ============================================================

def analyze_symbol(
    exchange: ccxt.binance,
    symbol: str,
) -> dict[str, Any]:
    candles = fetch_ohlcv(exchange, symbol)
    df = candles_to_dataframe(candles)
    close = df["close"]
    price = float(close.iloc[-1])

    ema20_series = close.ewm(span=20, adjust=False).mean()
    ema50_series = close.ewm(span=50, adjust=False).mean()
    ema20 = float(ema20_series.iloc[-1])
    ema50 = float(ema50_series.iloc[-1])

    rsi = calculate_rsi(close)
    momentum = calculate_momentum_4h(df)
    relative_volume = calculate_relative_volume(df)
    atr_raw = calculate_atr_raw(df)
    atr_percent = calculate_atr(df)

    trend1 = trend_points_1h(price, ema20, ema50)

    df4 = resample_4h(df)
    if len(df4) >= 55:
        close4 = df4["close"]
        ema20_4h_series = close4.ewm(span=20, adjust=False).mean()
        ema50_4h_series = close4.ewm(span=50, adjust=False).mean()
        price_4h = float(close4.iloc[-1])
        ema20_4h = float(ema20_4h_series.iloc[-1])
        ema50_4h = float(ema50_4h_series.iloc[-1])
    else:
        price_4h = float(df4["close"].iloc[-1]) if len(df4) else 0.0
        ema20_4h = 0.0
        ema50_4h = 0.0

    trend4 = trend_points_4h(df4)
    rsi_pts = rsi_points(rsi)
    mom_pts = momentum_points(momentum)
    vol_pts = volume_points(relative_volume)
    volat_pts = volatility_points(atr_percent)

    # Score histórico do V3: 20 + 25 + 20 + 15 + 15 = 95.
    # Mantemos a mesma lógica de score do arquivo enviado para não
    # alterar o comportamento do radar durante a correção do banco.
    score = max(0, min(100, int(rsi_pts + trend1 + trend4 + mom_pts + vol_pts)))

    risks = risk_flags(
        rsi=rsi,
        momentum=momentum,
        atr_percent=atr_percent,
        relative_volume=relative_volume,
    )

    conf = confidence(
        score=score,
        trend_1h=trend1,
        trend_4h=trend4,
        momentum=momentum,
        relative_volume=relative_volume,
        risks=risks,
    )

    classification = classify(score)
    sig = signal(score)
    timestamp = df["timestamp"].iloc[-1].isoformat()

    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "price": price,
        "rsi": rsi,
        "ema20": ema20,
        "ema50": ema50,
        "price_4h": price_4h,
        "ema20_4h": ema20_4h,
        "ema50_4h": ema50_4h,
        "trend_1h": trend1,
        "trend_4h": trend4,
        "momentum_4h": momentum,
        "relative_volume": relative_volume,
        "atr": atr_raw,
        "atr_percent": atr_percent,
        "volatility": atr_percent,
        "rsi_points": rsi_pts,
        "trend_1h_points": trend1,
        "trend_4h_points": trend4,
        "momentum_points": mom_pts,
        "volume_points": vol_pts,
        "volatility_points": volat_pts,
        "score": score,
        "classification": classification,
        "signal": sig,
        "confidence": conf,
        "risks": risks,
        "risk_flags": risks,
        "risk_count": len(risks),
        "momentum": momentum,
        "volume": relative_volume,
        "volume_relative": relative_volume,
    }


# ============================================================
# MERCADOS
# ============================================================

def load_candidate_markets(
    exchange: ccxt.binance,
) -> list[str]:

    markets = exchange.load_markets()

    candidates: list[str] = []

    for symbol, market in markets.items():

        if not market.get("active", False):
            continue

        if market.get("spot") is not True:
            continue

        if market.get("quote") != "USDT":
            continue

        if market.get("base") == "USDT":
            continue

        candidates.append(symbol)

    return candidates


def select_markets(
    exchange: ccxt.binance,
    candidates: list[str],
) -> list[str]:

    print("Buscando tickers...")

    selected: list[tuple[str, float]] = []

    # Busca em lotes para evitar URL gigantes.
    batch_size = 50

    for start in range(
        0,
        len(candidates),
        batch_size,
    ):

        batch = candidates[
            start:start + batch_size
        ]

        try:
            tickers = exchange.fetch_tickers(batch)

        except Exception:
            # Fallback individual.
            tickers = {}

            for symbol in batch:
                try:
                    tickers[symbol] = (
                        exchange.fetch_ticker(symbol)
                    )
                except Exception:
                    continue

        for symbol, ticker in tickers.items():

            quote_volume = ticker.get(
                "quoteVolume"
            )

            if quote_volume is None:
                continue

            try:
                quote_volume = float(
                    quote_volume
                )
            except (TypeError, ValueError):
                continue

            if quote_volume < MIN_VOLUME_USDT:
                continue

            selected.append(
                (
                    symbol,
                    quote_volume,
                )
            )

    selected.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    return [
        symbol
        for symbol, _ in selected[:TOP_MARKETS]
    ]


def listing_age_days(
    exchange: ccxt.binance,
    symbol: str,
) -> float | None:
    """Idade (em dias) do candle diário mais antigo disponível.

    Usado como proxy da data de listagem do par spot, já que a
    Binance não expõe isso em load_markets(). Retorna None se não
    for possível determinar (erro de rede, símbolo sem histórico).
    """
    try:
        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe="1d",
            since=0,
            limit=1,
        )
    except Exception:
        return None

    if not candles:
        return None

    first_ms = candles[0][0]
    age = (
        datetime.now(timezone.utc)
        - datetime.fromtimestamp(first_ms / 1000, tz=timezone.utc)
    )
    return age.total_seconds() / 86400.0


def filter_by_listing_age(
    exchange: ccxt.binance,
    markets: list[str],
    min_days: int = MIN_LISTING_AGE_DAYS,
) -> list[str]:
    """Remove símbolos listados há menos de min_days dias.

    Roda só sobre os mercados já pré-selecionados (não sobre todos os
    candidatos), então é uma chamada leve (1 candle diário) por
    símbolo, não uma busca completa de histórico.
    """
    kept = []
    for symbol in markets:
        age = listing_age_days(exchange, symbol)
        if age is None:
            # Não deu pra confirmar a idade - mantém por segurança
            # (não penaliza um símbolo por falha de rede transitória).
            kept.append(symbol)
            continue
        if age < min_days:
            print(
                f"  Ignorando {symbol}: listado há "
                f"{age:.0f}d (< {min_days}d mínimo)"
            )
            continue
        kept.append(symbol)
    return kept


# ============================================================
# IMPRESSÃO
# ============================================================

def print_header() -> None:

    print()
    print("=" * 70)
    print(
        "                      CRYPTO RADAR - SCANNER V3"
    )
    print("=" * 70)

    print(f"Timeframe:        {TIMEFRAME}")
    print(f"Candles:          {CANDLES}")
    print(f"TOP mercados:     {TOP_MARKETS}")
    print(
        f"Volume mínimo:    ${MIN_VOLUME_USDT / 1_000_000:.2f}M"
    )
    print(
        f"Timeout rede:     {NETWORK_TIMEOUT_MS / 1000:.0f}s"
    )
    print(
        f"Retry OHLCV:      {OHLCV_RETRIES}"
    )
    print(
        "Usando somente candles fechados."
    )
    print()


def print_analysis(r: dict[str, Any]) -> None:

    print(
        f"  Preço:                     "
        f"{r['price']:.8f}"
    )

    print(
        f"  RSI:                       "
        f"{r['rsi']:.2f}"
    )

    print(
        f"  EMA20:                     "
        f"{r['ema20']:.8f}"
    )

    print(
        f"  EMA50:                     "
        f"{r['ema50']:.8f}"
    )

    print(
        f"  Momentum 4h:               "
        f"{r['momentum_4h']:+.2f}%"
    )

    print(
        f"  Volume relativo:           "
        f"{r['relative_volume']:.2f}x"
    )

    print(
        f"  ATR:                       "
        f"{r['atr_percent']:.2f}%"
    )

    print()
    print("  COMPONENTES DO SCORE")
    print(
        "  -------------------------------------------------------------"
    )

    print(
        f"  RSI:               "
        f"{r['rsi_points']:>3}/20"
    )

    print(
        f"  Tendência 1h:      "
        f"{r['trend_1h_points']:>3}/25"
    )

    print(
        f"  Tendência 4h:      "
        f"{r['trend_4h_points']:>3}/20"
    )

    print(
        f"  Momentum:           "
        f"{r['momentum_points']:>3}/15"
    )

    print(
        f"  Volume:             "
        f"{r['volume_points']:>3}/15"
    )

    print(
        "  -------------------------------------------------------------"
    )

    print(
        f"  SCORE:              "
        f"{r['score']:>3}/100"
    )

    print(
        f"  Classificação:     "
        f"{r['classification']}"
    )

    print(
        f"  Sinal:             "
        f"{r['signal']}"
    )

    print(
        f"  Confiança:         "
        f"{r['confidence']:>3}%"
    )

    if r["risks"]:
        print(
            "  Riscos:            "
            + ", ".join(r["risks"])
        )


def print_ranking(
    results: list[dict[str, Any]],
) -> None:

    ranking = sorted(
        results,
        key=lambda r: (
            r["score"],
            r["confidence"],
            r["relative_volume"],
        ),
        reverse=True,
    )

    print()
    print("=" * 120)
    print(
        "                                        RANKING DETALHADO V3"
    )
    print("=" * 120)

    print(
        " # MERCADO         SCORE RSI T1H T4H  MOM  VOL   ATR  RVOL  CONF CLASSIFICAÇÃO"
    )

    print("-" * 120)

    for index, r in enumerate(
        ranking,
        start=1,
    ):

        print(
            f"{index:2d} "
            f"{r['symbol']:<16} "
            f"{r['score']:>5} "
            f"{r['rsi_points']:>3} "
            f"{r['trend_1h_points']:>3} "
            f"{r['trend_4h_points']:>3} "
            f"{r['momentum_points']:>4} "
            f"{r['volume_points']:>4} "
            f"{r['atr_percent']:>5.2f} "
            f"{r['relative_volume']:>5.2f} "
            f"{r['confidence']:>5} "
            f"{r['classification']}"
        )

    print("=" * 120)

    print()
    print("=" * 70)
    print(
        "                         TOP 10 V3"
    )
    print("=" * 70)

    for index, r in enumerate(
        ranking[:TOP_10],
        start=1,
    ):

        print(
            f"{index:2d}. "
            f"{r['symbol']:<15} "
            f"{r['score']:>3}/100 "
            f"{r['classification']:<15} "
            f"CONF {r['confidence']:>3}% "
            f"{r['signal']}"
        )

    print("=" * 70)


def print_signals(
    results: list[dict[str, Any]],
) -> None:

    selected = [
        r
        for r in results
        if r["score"] >= 65
        and r["confidence"] >= 65
    ]

    selected.sort(
        key=lambda r: (
            r["score"],
            r["confidence"],
            r["relative_volume"],
        ),
        reverse=True,
    )

    print()
    print("=" * 70)
    print(
        "                        SINAIS V3"
    )
    print("=" * 70)

    if not selected:
        print(
            "Nenhum sinal com score e confiança suficientes."
        )

        print("=" * 70)
        return

    for index, r in enumerate(
        selected,
        start=1,
    ):

        print(
            f"{index:2d}. "
            f"{r['symbol']:<15} "
            f"SCORE {r['score']:>3}  "
            f"CONF {r['confidence']:>3}%  "
            f"{r['signal']}"
        )

        if r["risks"]:
            print(
                "    Riscos: "
                + ", ".join(r["risks"])
            )

    print("=" * 70)


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    start_time = time.time()
    run_at = datetime.now(timezone.utc).isoformat()

    print_header()

    # --------------------------------------------------------
    # Banco
    # --------------------------------------------------------

    print("Inicializando banco...")

    try:
        init_database()
        print("✓ Banco OK")

    except Exception as exc:
        print(
            f"✗ Erro banco: {type(exc).__name__}: {exc}"
        )
        return

    # --------------------------------------------------------
    # Binance
    # --------------------------------------------------------

    print("Inicializando Binance...")

    try:
        exchange = create_exchange()

        # Teste de conexão.
        exchange.load_markets()

        print("✓ Binance OK")

    except Exception as exc:
        print(
            f"✗ Erro Binance: {type(exc).__name__}: {exc}"
        )
        return

    # --------------------------------------------------------
    # Mercados
    # --------------------------------------------------------

    print()
    print("Carregando mercados...")

    try:
        candidates = load_candidate_markets(
            exchange
        )

        print(
            f"Mercados candidatos: {len(candidates)}"
        )

    except Exception as exc:
        print(
            f"✗ Erro mercados: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    # --------------------------------------------------------
    # Seleção
    # --------------------------------------------------------

    try:
        markets = select_markets(
            exchange,
            candidates,
        )

        print(
            f"Mercados selecionados: {len(markets)}"
        )

    except Exception as exc:
        print(
            f"✗ Erro tickers: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    # --------------------------------------------------------
    # Filtro de idade de listagem
    # --------------------------------------------------------

    print()
    print(f"Filtrando por idade de listagem (mín. {MIN_LISTING_AGE_DAYS}d)...")

    try:
        markets = filter_by_listing_age(exchange, markets)
        print(f"Mercados após filtro de idade: {len(markets)}")
    except Exception as exc:
        print(
            f"✗ Erro filtro de idade: "
            f"{type(exc).__name__}: {exc} - seguindo sem filtrar"
        )

    # --------------------------------------------------------
    # Análise
    # --------------------------------------------------------

    print()
    print("Analisando mercados...")
    print("-" * 70)

    results: list[dict[str, Any]] = []
    errors = 0

    for index, symbol in enumerate(
        markets,
        start=1,
    ):

        item_start = time.time()

        print(
            f"[{index:02d}/{len(markets):02d}] "
            f"{symbol}"
        )

        try:

            result = analyze_symbol(
                exchange,
                symbol,
            )

            results.append(result)

            print_analysis(result)

        except Exception as exc:

            errors += 1

            print(
                f"  Aviso: "
                f"{type(exc).__name__}: {exc}"
            )

        elapsed = time.time() - item_start

        print(
            f"  ✓ Concluído em {elapsed:.2f}s"
        )

    # --------------------------------------------------------
    # Ranking
    # --------------------------------------------------------

    if results:

        print_ranking(results)

        print_signals(results)

    # --------------------------------------------------------
    # Banco
    # --------------------------------------------------------

    saved = 0

    if results:

        print()
        print(
            "Salvando análises V3 no banco..."
        )

        try:

            saved = save_results(
                results,
                run_at
            )

            print(
                f"✓ {saved} análises V3 salvas"
            )

        except Exception as exc:

            errors += 1

            print(
                f"✗ Erro ao salvar: "
                f"{type(exc).__name__}: {exc}"
            )

    # --------------------------------------------------------
    # Resumo
    # --------------------------------------------------------

    total_time = time.time() - start_time

    print()
    print("=" * 70)
    print(
        "                        RESUMO V3"
    )
    print("=" * 70)

    print(
        f"Mercados selecionados: {len(markets)}"
    )

    print(
        f"Análises concluídas:   {len(results)}"
    )

    print(
        f"Análises salvas:       {saved}"
    )

    print(
        f"Erros/avisos:          {errors}"
    )

    print(
        f"Tempo total:           {total_time:.2f}s"
    )

    print(
        f"Banco:                 {DB_PATH}"
    )

    print(
        "Tabela V3:             scanner_v3_results"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()
