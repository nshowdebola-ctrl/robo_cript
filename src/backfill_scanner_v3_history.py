#!/usr/bin/env python3
"""
CRYPTO RADAR - BACKFILL SCANNER V3 HISTORY

Objetivo:
    Aumentar o histórico da tabela scanner_v3_results usando candles 1h
    históricos da Binance, sem apagar as observações existentes.

Uso:
    python src/backfill_scanner_v3_history.py --hours 720
    python src/backfill_scanner_v3_history.py --hours 1680 --max-symbols 61

O script:
    - usa os símbolos já presentes em scanner_v3_results;
    - baixa candles 1h históricos por símbolo;
    - calcula indicadores compatíveis com o V3;
    - grava somente timestamps/símbolos ainda ausentes;
    - não altera nem apaga dados existentes;
    - pode ser executado novamente com segurança.

Recomendação:
    Começar com 720 horas (30 dias). Depois aumentar para 1680 (70 dias)
    se a Binance disponibilizar o histórico normalmente.
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "crypto_radar.db"

TIMEFRAME = "1h"
FETCH_LIMIT = 1000
NETWORK_TIMEOUT_MS = 15_000
DB_TIMEOUT = 30
DB_RETRIES = 8

# Colunas usadas pelo scanner_v3_final.py.
COLUMNS = [
    "timestamp", "symbol", "timeframe", "price",
    "rsi", "ema20", "ema50",
    "price_4h", "ema20_4h", "ema50_4h",
    "momentum_4h", "relative_volume",
    "atr", "atr_percent", "volatility",
    "rsi_points", "trend_1h_points", "trend_4h_points",
    "momentum_points", "volume_points", "volatility_points",
    "score", "classification", "signal", "confidence",
    "risk_flags", "risk_count",
    "trend_1h", "trend_4h", "momentum", "volume",
    "volume_relative", "risks",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill histórico do scanner_v3_results."
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=720,
        help="Quantidade de horas históricas a buscar (default: 720 = 30 dias).",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="Limita quantidade de símbolos; 0 = todos os símbolos existentes.",
    )
    parser.add_argument(
        "--since",
        type=str,
        default="",
        help="Início UTC opcional, formato YYYY-MM-DDTHH:MM:SSZ.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calcula e mostra quantas linhas seriam inseridas, sem gravar.",
    )
    return parser.parse_args()


def connect_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    db.execute("PRAGMA busy_timeout = 30000")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    return db


def ensure_schema() -> None:
    """Garante as colunas necessárias sem apagar dados."""
    db = connect_db()
    try:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS scanner_v3_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        existing = {
            row[1]
            for row in db.execute("PRAGMA table_info(scanner_v3_results)")
        }

        additions = {
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
                db.execute(
                    f"ALTER TABLE scanner_v3_results ADD COLUMN {column} {definition}"
                )

        db.commit()
    finally:
        db.close()


def get_existing_symbols() -> list[str]:
    db = connect_db()
    try:
        rows = db.execute(
            """
            SELECT symbol, COUNT(*) AS n
            FROM scanner_v3_results
            WHERE timeframe = '1h'
            GROUP BY symbol
            ORDER BY n DESC, symbol ASC
            """
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        db.close()


def get_existing_keys(symbol: str) -> set[str]:
    db = connect_db()
    try:
        rows = db.execute(
            """
            SELECT timestamp
            FROM scanner_v3_results
            WHERE symbol = ? AND timeframe = '1h'
            """,
            (symbol,),
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        db.close()


def create_exchange() -> ccxt.binance:
    return ccxt.binance(
        {
            "enableRateLimit": True,
            "timeout": NETWORK_TIMEOUT_MS,
            "options": {"defaultType": "spot"},
        }
    )


def parse_since(value: str, hours: int) -> int:
    if value:
        text = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours + 80)
    return int(start.timestamp() * 1000)


def fetch_history(
    exchange: ccxt.binance,
    symbol: str,
    since_ms: int,
    target_hours: int,
) -> list[list[float]]:
    """Baixa o intervalo em páginas de até 1000 candles."""
    timeframe_ms = exchange.parse_timeframe(TIMEFRAME) * 1000
    target_end_ms = exchange.milliseconds() - timeframe_ms
    needed = target_hours + 80

    candles: dict[int, list[float]] = {}
    cursor = since_ms

    while cursor <= target_end_ms and len(candles) < needed + 20:
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                batch = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=TIMEFRAME,
                    since=cursor,
                    limit=min(FETCH_LIMIT, needed + 20 - len(candles)),
                )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(attempt)

        if last_error is not None:
            raise RuntimeError(
                f"falha ao buscar {symbol}: {last_error}"
            )

        if not batch:
            break

        for candle in batch:
            ts = int(candle[0])
            if ts <= target_end_ms:
                candles[ts] = candle

        last_ts = int(batch[-1][0])

        if last_ts <= cursor:
            break

        cursor = last_ts + timeframe_ms

        if len(batch) < FETCH_LIMIT:
            break

        time.sleep(exchange.rateLimit / 1000)

    ordered = [candles[k] for k in sorted(candles)]
    return ordered


def candles_to_dataframe(candles: list[list[float]]) -> pd.DataFrame:
    df = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], unit="ms", utc=True
    )

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = (
        df.dropna()
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    return df


def calculate_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
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

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.astype("float64")

    # Mesmo comportamento prático do scanner quando não há perda.
    rsi[(avg_loss == 0) & (avg_gain > 0)] = 100.0
    return rsi


def calculate_atr_series(
    df: pd.DataFrame,
    period: int = 14,
) -> pd.Series:
    previous_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - previous_close).abs()
    tr3 = (df["low"] - previous_close).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(period).mean()


def trend_points_1h(price: float, ema20: float, ema50: float) -> int:
    if price > ema20 > ema50:
        return 25
    if price > ema20 and ema20 <= ema50:
        return 15
    if price > ema50:
        return 15
    return 0


def trend_points_4h_from_window(df4: pd.DataFrame) -> int:
    if len(df4) < 55:
        return 0

    close4 = df4["close"]
    ema20 = close4.ewm(span=20, adjust=False).mean()
    ema50 = close4.ewm(span=50, adjust=False).mean()

    price = float(close4.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])

    if price > e20 > e50:
        return 20
    if price > e20:
        return 14
    if price > e50:
        return 7
    return 0


def rsi_points(rsi: float) -> int:
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
    if atr_percent <= 1.0:
        return 10
    if atr_percent <= 2.0:
        return 8
    if atr_percent <= 3.0:
        return 5
    if atr_percent <= 5.0:
        return 2
    return 0


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


def confidence(
    score: int,
    trend_1h: int,
    trend_4h: int,
    momentum: float,
    relative_volume: float,
    risks: list[str],
) -> int:
    value = 0

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

    if trend_1h >= 25:
        value += 20
    elif trend_1h >= 15:
        value += 12

    if trend_4h >= 20:
        value += 20
    elif trend_4h >= 14:
        value += 14
    elif trend_4h > 0:
        value += 7

    if momentum >= 2:
        value += 10
    elif momentum >= 1:
        value += 8
    elif momentum >= 0.5:
        value += 5
    elif momentum >= 0:
        value += 2

    if relative_volume >= 2:
        value += 15
    elif relative_volume >= 1.5:
        value += 12
    elif relative_volume >= 1:
        value += 8
    elif relative_volume >= 0.5:
        value += 4

    if "RSI_SOBRECOMPRADO" in risks:
        value -= 7
    if "MOMENTUM_NEGATIVO" in risks:
        value -= 10
    if "VOLATILIDADE_ALTA" in risks:
        value -= 8
    if "VOLUME_BAIXO" in risks:
        value -= 8

    return max(0, min(100, int(value)))


def build_rows(
    symbol: str,
    df: pd.DataFrame,
    existing_keys: set[str],
) -> list[tuple[Any, ...]]:
    """
    Gera uma observação por candle fechado.

    Mantemos uma janela de contexto grande para que RSI/EMA/ATR e a
    tendência 4H não sejam calculados a partir de poucos candles.
    """
    if len(df) < 240:
        return []

    close = df["close"]

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    rsi = calculate_rsi_series(close)
    atr_raw = calculate_atr_series(df)

    rel_volume = (
        df["volume"] / df["volume"].rolling(20).mean()
    )

    momentum = (
        (close / close.shift(4) - 1.0) * 100.0
    )

    # 4H agregado sobre todo o histórico.
    data4 = (
        df.set_index("timestamp")
        .resample("4h")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
        .reset_index()
    )

    # Mapa de cada candle 1h para o último candle 4h fechado.
    data4["ema20_4h"] = data4["close"].ewm(
        span=20, adjust=False
    ).mean()
    data4["ema50_4h"] = data4["close"].ewm(
        span=50, adjust=False
    ).mean()

    data4["trend_4h"] = 0
    valid4 = data4["close"].notna()

    for i in range(len(data4)):
        if i < 54:
            continue

        p = float(data4.at[i, "close"])
        e20 = float(data4.at[i, "ema20_4h"])
        e50 = float(data4.at[i, "ema50_4h"])

        if p > e20 > e50:
            data4.at[i, "trend_4h"] = 20
        elif p > e20:
            data4.at[i, "trend_4h"] = 14
        elif p > e50:
            data4.at[i, "trend_4h"] = 7

    data4 = data4[
        ["timestamp", "close", "ema20_4h", "ema50_4h", "trend_4h"]
    ].rename(columns={"close": "price_4h"})

    # merge_asof: usa somente o 4H cujo timestamp já ocorreu.
    work = pd.merge_asof(
        df.sort_values("timestamp"),
        data4.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )

    work["ema20"] = ema20.values
    work["ema50"] = ema50.values
    work["rsi"] = rsi.values
    work["atr"] = atr_raw.values
    work["atr_percent"] = (
        work["atr"] / work["close"] * 100.0
    )
    work["relative_volume"] = rel_volume.values
    work["momentum_4h"] = momentum.values

    rows: list[tuple[Any, ...]] = []

    for _, row in work.iterrows():
        ts = row["timestamp"].isoformat()

        if ts in existing_keys:
            continue

        values = [
            row["close"],
            row["rsi"],
            row["ema20"],
            row["ema50"],
            row["atr"],
            row["atr_percent"],
            row["relative_volume"],
            row["momentum_4h"],
        ]

        if any(pd.isna(x) for x in values):
            continue

        price = float(row["close"])
        r = float(row["rsi"])
        e20 = float(row["ema20"])
        e50 = float(row["ema50"])
        atr = float(row["atr"])
        atr_pct = float(row["atr_percent"])
        rv = float(row["relative_volume"])
        mom = float(row["momentum_4h"])

        trend1 = trend_points_1h(price, e20, e50)
        trend4 = int(row["trend_4h"]) if not pd.isna(row["trend_4h"]) else 0

        p4 = float(row["price_4h"]) if not pd.isna(row["price_4h"]) else 0.0
        e20_4 = (
            float(row["ema20_4h"])
            if not pd.isna(row["ema20_4h"])
            else 0.0
        )
        e50_4 = (
            float(row["ema50_4h"])
            if not pd.isna(row["ema50_4h"])
            else 0.0
        )

        rsi_pts = rsi_points(r)
        trend1_pts = trend1
        trend4_pts = trend4
        mom_pts = momentum_points(mom)
        vol_pts = volume_points(rv)
        volat_pts = volatility_points(atr_pct)

        score = max(
            0,
            min(
                100,
                int(
                    rsi_pts
                    + trend1_pts
                    + trend4_pts
                    + mom_pts
                    + vol_pts
                ),
            ),
        )

        risks = risk_flags(r, mom, atr_pct, rv)
        conf = confidence(
            score,
            trend1,
            trend4,
            mom,
            rv,
            risks,
        )

        classification = classify(score)
        sig = signal(score)
        risk_text = ",".join(risks)

        rows.append(
            (
                ts,
                symbol,
                TIMEFRAME,
                price,
                r,
                e20,
                e50,
                p4,
                e20_4,
                e50_4,
                mom,
                rv,
                atr,
                atr_pct,
                atr_pct,
                rsi_pts,
                trend1_pts,
                trend4_pts,
                mom_pts,
                vol_pts,
                volat_pts,
                score,
                classification,
                sig,
                conf,
                risk_text,
                len(risks),
                trend1,
                trend4,
                mom,
                rv,
                rv,
                risk_text,
            )
        )

    return rows


def insert_rows(rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0

    placeholders = ", ".join("?" for _ in COLUMNS)

    for attempt in range(1, DB_RETRIES + 1):
        db = None
        try:
            db = connect_db()
            db.executemany(
                f"""
                INSERT INTO scanner_v3_results
                ({", ".join(COLUMNS)})
                VALUES ({placeholders})
                """,
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


def database_stats() -> tuple[int, str | None, str | None]:
    db = connect_db()
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM scanner_v3_results"
        ).fetchone()[0]

        first_ts, last_ts = db.execute(
            """
            SELECT MIN(timestamp), MAX(timestamp)
            FROM scanner_v3_results
            WHERE timeframe = '1h'
            """
        ).fetchone()

        return int(total), first_ts, last_ts
    finally:
        db.close()


def main() -> None:
    args = parse_args()

    if args.hours < 240:
        raise SystemExit(
            "--hours deve ser >= 240 para formar contexto suficiente."
        )

    print("=" * 100)
    print("CRYPTO RADAR - BACKFILL HISTÓRICO SCANNER V3")
    print("=" * 100)
    print(f"Banco: {DB_PATH}")
    print(f"Histórico solicitado: {args.hours} horas")
    print(f"Modo: {'DRY-RUN' if args.dry_run else 'GRAVAÇÃO'}")
    print("=" * 100)

    if not DB_PATH.exists():
        raise SystemExit(f"Banco não encontrado: {DB_PATH}")

    ensure_schema()

    symbols = get_existing_symbols()

    if args.max_symbols > 0:
        symbols = symbols[: args.max_symbols]

    if not symbols:
        raise SystemExit(
            "Nenhum símbolo encontrado em scanner_v3_results."
        )

    since_ms = parse_since(args.since, args.hours)

    exchange = create_exchange()
    exchange.load_markets()

    print(f"Símbolos selecionados: {len(symbols)}")
    print(
        "Início aproximado:",
        datetime.fromtimestamp(
            since_ms / 1000,
            tz=timezone.utc,
        ).isoformat(),
    )
    print()

    total_downloaded = 0
    total_generated = 0
    total_inserted = 0
    errors = 0

    for index, symbol in enumerate(symbols, start=1):
        print(
            f"[{index:02d}/{len(symbols):02d}] "
            f"{symbol:<18}",
            end=" ",
            flush=True,
        )

        try:
            if symbol not in exchange.markets:
                print("IGNORADO: mercado não encontrado")
                continue

            candles = fetch_history(
                exchange,
                symbol,
                since_ms,
                args.hours,
            )

            total_downloaded += len(candles)

            if not candles:
                print("sem candles")
                continue

            df = candles_to_dataframe(candles)

            existing = get_existing_keys(symbol)
            rows = build_rows(symbol, df, existing)

            total_generated += len(rows)

            if args.dry_run:
                print(
                    f"{len(candles)} candles | "
                    f"{len(rows)} novas observações"
                )
            else:
                inserted = insert_rows(rows)
                total_inserted += inserted
                print(
                    f"{len(candles)} candles | "
                    f"{inserted} inseridas"
                )

        except Exception as exc:
            errors += 1
            print(
                f"ERRO: {type(exc).__name__}: {exc}"
            )

    total, first_ts, last_ts = database_stats()

    print()
    print("=" * 100)
    print("RESUMO")
    print("=" * 100)
    print(f"Símbolos processados:     {len(symbols)}")
    print(f"Candles baixados:         {total_downloaded}")
    print(f"Observações geradas:      {total_generated}")
    print(f"Observações inseridas:    {total_inserted}")
    print(f"Erros:                    {errors}")
    print(f"Total no banco:           {total}")
    print(f"Primeira observação:      {first_ts}")
    print(f"Última observação:        {last_ts}")
    print("=" * 100)

    if not args.dry_run:
        print()
        print("Próximo passo:")
        print("python src/backtest_v4_validator.py --limit 2700")


if __name__ == "__main__":
    main()
