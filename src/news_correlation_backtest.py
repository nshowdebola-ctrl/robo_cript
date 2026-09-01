#!/usr/bin/env python3
"""
CRYPTO RADAR - NEWS RADAR V1 - FASE 2
Correlação entre sentimento de notícia e retorno futuro de preço.

Metodologia:
- Cada manchete com símbolo(s) casado(s) vira uma observação por
  símbolo (uma manchete citando "BTC,ETH" gera 2 observações).
- Preço de referência ("preço na notícia") é o candle 1h mais recente
  com timestamp <= published_at (sem espiar o futuro).
- Retorno futuro em cada horizonte (1h/4h/24h) usa o candle mais
  próximo de published_at + horizonte, também sem espiar além do que
  já existe no histórico.
- Compara retorno médio/mediano entre manchetes POSITIVO vs NEGATIVO
  vs NEUTRO, e calcula correlação (Pearson) entre sentiment_score
  contínuo e o retorno em cada horizonte.
- Além do retorno bruto, calcula também o retorno em EXCESSO ao BTC
  (retorno do símbolo menos retorno do BTC na mesma janela) - remove
  o efeito de "todo o mercado subiu/caiu junto", que é ruído grande
  demais pra tentar isolar o efeito de uma notícia específica.
  Observações do próprio BTC não entram nessa parte (excesso de BTC
  contra BTC é sempre ~0, não informa nada).
- Não abre posição nem inventa trade - é um estudo de correlação, não
  uma simulação de carteira.

IMPORTANTE: com pouco dado (poucos dias de coleta), qualquer leitura
aqui é preliminar. O script foi feito para ser re-executado conforme
o histórico de notícias crescer - o método já está certo, falta tempo
de coleta para ter poder estatístico real.

Uso:
  python3 src/news_correlation_backtest.py
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NEWS_DB = ROOT / "data" / "news_radar.db"
OUTPUT_CSV = ROOT / "data" / "news_correlation_observations.csv"

HORIZONS_HOURS = [1, 4, 24]
MIN_OBSERVATIONS_FOR_STATS = 30


@dataclass
class Observation:
    symbol: str
    published_at: datetime
    sentiment_score: float
    sentiment_label: str
    title: str


def load_observations(conn: sqlite3.Connection) -> list[Observation]:
    rows = conn.execute(
        """
        SELECT symbols_matched, published_at, sentiment_score, sentiment_label, title
        FROM news_items
        WHERE symbols_matched != ''
        """
    ).fetchall()

    out = []
    for symbols_matched, published_at, score, label, title in rows:
        try:
            dt = datetime.fromisoformat(published_at)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        for symbol in symbols_matched.split(","):
            symbol = symbol.strip()
            if not symbol:
                continue
            out.append(Observation(
                symbol=symbol,
                published_at=dt,
                sentiment_score=float(score or 0.0),
                sentiment_label=label or "NEUTRO",
                title=title,
            ))
    return out


def fetch_history(exchange: ccxt.binance, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    market = f"{symbol}/USDT"
    all_candles = []
    since = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    while since < end_ms:
        try:
            batch = exchange.fetch_ohlcv(market, timeframe="1h", since=since, limit=1000)
        except Exception as exc:
            print(f"  AVISO {market}: falha ao buscar candles ({exc})")
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
        return pd.DataFrame(columns=["timestamp", "close"])

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df[["timestamp", "close"]]


def price_at_or_before(df: pd.DataFrame, when: datetime) -> float | None:
    if df.empty:
        return None
    eligible = df[df["timestamp"] <= pd.Timestamp(when)]
    if eligible.empty:
        return None
    return float(eligible.iloc[-1]["close"])


def main() -> int:
    conn = sqlite3.connect(NEWS_DB)
    observations = load_observations(conn)

    if len(observations) < 5:
        print("Poucas observações com símbolo casado - nada a analisar ainda.")
        return 1

    symbols = sorted({o.symbol for o in observations})
    print(f"Observações (manchete x símbolo): {len(observations)}")
    print(f"Símbolos distintos: {len(symbols)}")
    print("Baixando histórico de preços na Binance...")

    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})

    price_history: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        symbol_obs = [o for o in observations if o.symbol == symbol]
        start = min(o.published_at for o in symbol_obs) - timedelta(hours=1)
        end = max(o.published_at for o in symbol_obs) + timedelta(hours=max(HORIZONS_HOURS) + 2)
        df = fetch_history(exchange, symbol, start, end)
        price_history[symbol] = df
        print(f"  {symbol:10s} {len(df)} candles")

    if "BTC" in price_history:
        btc_df = price_history["BTC"]
    else:
        btc_start = min(o.published_at for o in observations) - timedelta(hours=1)
        btc_end = max(o.published_at for o in observations) + timedelta(hours=max(HORIZONS_HOURS) + 2)
        btc_df = fetch_history(exchange, "BTC", btc_start, btc_end)
        print(f"  {'BTC':10s} {len(btc_df)} candles (referência p/ retorno em excesso)")

    print()
    print("Calculando retornos por horizonte...")

    records = []
    for o in observations:
        df = price_history.get(o.symbol)
        if df is None or df.empty:
            continue

        base_price = price_at_or_before(df, o.published_at)
        if base_price is None or base_price <= 0:
            continue

        row = {
            "symbol": o.symbol,
            "published_at": o.published_at.isoformat(),
            "sentiment_score": o.sentiment_score,
            "sentiment_label": o.sentiment_label,
            "title": o.title,
        }
        btc_base_price = None
        if o.symbol != "BTC" and not btc_df.empty:
            btc_base_price = price_at_or_before(btc_df, o.published_at)

        has_any_horizon = False
        for h in HORIZONS_HOURS:
            future_price = price_at_or_before(df, o.published_at + timedelta(hours=h))
            if future_price is None:
                row[f"return_{h}h"] = None
                row[f"return_{h}h_ex_btc"] = None
                continue
            symbol_return = (future_price / base_price - 1.0) * 100.0
            row[f"return_{h}h"] = symbol_return
            has_any_horizon = True

            excess = None
            if btc_base_price is not None and btc_base_price > 0:
                btc_future_price = price_at_or_before(btc_df, o.published_at + timedelta(hours=h))
                if btc_future_price is not None:
                    btc_return = (btc_future_price / btc_base_price - 1.0) * 100.0
                    excess = symbol_return - btc_return
            row[f"return_{h}h_ex_btc"] = excess

        if has_any_horizon:
            records.append(row)

    if not records:
        print("Nenhuma observação com retorno calculável (histórico de preço insuficiente).")
        return 1

    result_df = pd.DataFrame(records)
    result_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Observações com retorno calculado: {len(result_df)} (salvas em {OUTPUT_CSV})")

    print()
    print("=" * 100)
    print("RESULTADO - SENTIMENTO DE NOTÍCIA x RETORNO FUTURO")
    print("=" * 100)

    if len(result_df) < MIN_OBSERVATIONS_FOR_STATS:
        print(
            f"AVISO: só {len(result_df)} observações (< {MIN_OBSERVATIONS_FOR_STATS}). "
            "Qualquer padrão abaixo é preliminar - não é evidência estatística ainda, "
            "é só o método funcionando. Rode de novo depois de mais dias de coleta."
        )
        print()

    def print_block(col: str, title: str, df_in: pd.DataFrame) -> None:
        valid = df_in.dropna(subset=[col])
        if valid.empty:
            print(f"--- {title} (n=0) ---")
            print()
            return

        print(f"--- {title} (n={len(valid)}) ---")
        for label in ["POSITIVO", "NEUTRO", "NEGATIVO"]:
            subset = valid[valid["sentiment_label"] == label][col]
            if len(subset) == 0:
                print(f"  {label:9s}  n=0")
                continue
            print(
                f"  {label:9s}  n={len(subset):3d}  "
                f"média={statistics.mean(subset):+.3f}%  "
                f"mediana={statistics.median(subset):+.3f}%"
            )

        if len(valid) >= 3 and valid["sentiment_score"].nunique() > 1:
            corr = valid["sentiment_score"].corr(valid[col])
            print(f"  Correlação (Pearson, score contínuo x retorno): {corr:+.3f}")
        print()

    for h in HORIZONS_HOURS:
        col = f"return_{h}h"
        valid = result_df.dropna(subset=[col])
        if valid.empty:
            continue

        print_block(col, f"Horizonte {h}h - retorno BRUTO", result_df)

        excess_col = f"return_{h}h_ex_btc"
        excess_df = result_df[result_df["symbol"] != "BTC"]
        print_block(
            excess_col,
            f"Horizonte {h}h - retorno em EXCESSO ao BTC (exclui obs. de BTC)",
            excess_df,
        )

    print("=" * 100)
    print("Isto mede correlação, não causalidade, e o tamanho de amostra atual é")
    print("pequeno. Não usar para decisão de trade sem muito mais dado acumulado.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
