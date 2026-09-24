#!/usr/bin/env python3
"""
CRYPTO RADAR - NEWS RADAR - RODAPÉ DO PORTAL

Gera data/news_footer.json com as notícias mais recentes que citam
alguma cripto, cruzadas com o preço dela:
    - preço na hora da notícia (abertura da vela de 1h em que ela saiu -
      sem espiar o futuro) e variação desde então até agora;
    - a mesma variação descontando o BTC no mesmo intervalo (separa o
      movimento da moeda do "mercado inteiro subiu/caiu");
    - se o robô live está posicionado na moeda agora.
Mais um resumo da correlação histórica (sentimento x retorno 24h em
excesso ao BTC) lido de news_correlation_observations.csv.

Só leitura: dados públicos da Binance (sem chave), news_radar.db e os
CSVs do live. Não toma decisão de trade. Chamado no fim de cada ciclo do
news_collector.py; web/index.php só lê o JSON.

Uso:
  python3 src/news_footer.py
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NEWS_DB = DATA / "news_radar.db"
OBS_CSV = DATA / "news_correlation_observations.csv"
LIVE_OPEN = DATA / "binance_live_open_positions.csv"
OUT_JSON = DATA / "news_footer.json"

MAX_ITEMS = 15
LOOKBACK = timedelta(hours=48)
HOUR_MS = 3_600_000


def recent_news(conn: sqlite3.Connection) -> list[dict]:
    since = (datetime.now(timezone.utc) - LOOKBACK).isoformat()
    rows = conn.execute(
        """
        SELECT title, link, source, published_at, symbols_matched,
               sentiment_score, sentiment_label
        FROM news_items
        WHERE symbols_matched != '' AND published_at >= ?
        ORDER BY published_at DESC
        LIMIT ?
        """,
        (since, MAX_ITEMS),
    ).fetchall()
    keys = ["title", "link", "source", "published_at", "symbols",
            "sentiment_score", "sentiment_label"]
    return [dict(zip(keys, r)) for r in rows]


def hourly_opens(exchange, symbol: str, since_ms: int) -> dict[int, float] | None:
    """Abertura de cada vela de 1h desde since_ms, indexada pelo início."""
    try:
        candles = exchange.fetch_ohlcv(f"{symbol}/USDT", "1h", since=since_ms, limit=100)
    except Exception:
        return None
    return {c[0]: c[1] for c in candles}


def price_at(opens: dict[int, float] | None, published: datetime) -> float | None:
    if not opens:
        return None
    bucket = int(published.timestamp() * 1000) // HOUR_MS * HOUR_MS
    return opens.get(bucket)


def last_price(exchange, symbol: str) -> float | None:
    try:
        return float(exchange.fetch_ticker(f"{symbol}/USDT")["last"])
    except Exception:
        return None


def live_symbols() -> set[str]:
    try:
        with open(LIVE_OPEN, newline="", encoding="utf-8") as f:
            return {r["symbol"].split("/")[0].upper() for r in csv.DictReader(f)}
    except FileNotFoundError:
        return set()


def correlation_summary() -> dict | None:
    """Retorno médio 24h em excesso ao BTC por sentimento + Pearson."""
    try:
        with open(OBS_CSV, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("return_24h_ex_btc")]
    except FileNotFoundError:
        return None
    by_label: dict[str, list[float]] = {}
    xs, ys = [], []
    for r in rows:
        try:
            ret = float(r["return_24h_ex_btc"])
            score = float(r["sentiment_score"])
        except ValueError:
            continue
        by_label.setdefault(r["sentiment_label"], []).append(ret)
        xs.append(score)
        ys.append(ret)
    if len(xs) < 3:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    pearson = cov / (vx * vy) ** 0.5 if vx and vy else 0.0
    return {
        "n": len(xs),
        "pearson_24h_ex_btc": round(pearson, 3),
        "avg_24h_ex_btc": {
            label: {"n": len(v), "avg_pct": round(sum(v) / len(v), 2)}
            for label, v in sorted(by_label.items())
        },
        "updated_at": datetime.fromtimestamp(
            OBS_CSV.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def build() -> dict:
    conn = sqlite3.connect(NEWS_DB)
    try:
        news = recent_news(conn)
        total_news = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
    finally:
        conn.close()

    exchange = ccxt.binance({"enableRateLimit": True})
    since_ms = int((datetime.now(timezone.utc) - LOOKBACK - timedelta(hours=1)).timestamp() * 1000)
    symbols = {s for n in news for s in n["symbols"].split(",") if s} | {"BTC"}
    opens = {s: hourly_opens(exchange, s, since_ms) for s in sorted(symbols)}
    now_price = {s: last_price(exchange, s) for s in sorted(symbols)}
    holding = live_symbols()

    items = []
    for n in news:
        published = datetime.fromisoformat(n["published_at"])
        btc_then = price_at(opens["BTC"], published)
        btc_now = now_price["BTC"]
        btc_chg = (btc_now / btc_then - 1) * 100 if btc_then and btc_now else None
        coins = []
        for sym in n["symbols"].split(","):
            then, now = price_at(opens.get(sym), published), now_price.get(sym)
            chg = (now / then - 1) * 100 if then and now else None
            coins.append({
                "symbol": sym,
                "price_at_news": then,
                "price_now": now,
                "change_pct": round(chg, 2) if chg is not None else None,
                "change_ex_btc_pct": (
                    round(chg - btc_chg, 2)
                    if chg is not None and btc_chg is not None and sym != "BTC"
                    else None
                ),
                "live_holding": sym in holding,
            })
        items.append({
            "title": n["title"],
            "link": n["link"],
            "source": n["source"],
            "published_at": n["published_at"],
            "sentiment_label": n["sentiment_label"],
            "sentiment_score": n["sentiment_score"],
            "coins": coins,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_news": total_news,
        "items": items,
        "correlation": correlation_summary(),
    }


def main() -> int:
    payload = build()
    tmp = OUT_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, OUT_JSON)
    print(f"news_footer: {len(payload['items'])} notícias -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
