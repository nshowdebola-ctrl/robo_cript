#!/usr/bin/env python3
"""
CRYPTO RADAR - NEWS RADAR V1
Coletor de notícias (feeds RSS públicos) + sentimento léxico.

Escopo desta V1, combinado com o usuário:
- Projeto SEPARADO do pipeline paper_trading_v9_21.py em produção.
  Não lê nem escreve em data/crypto_radar.db, não mexe em
  forward_signals.csv, não abre/fecha posição nenhuma.
- Só coleta manchete + fonte + horário + símbolo(s) casados + sentimento
  léxico, e grava em data/news_radar.db (banco próprio).
- Não toma nenhuma decisão de trading. Isso é matéria da Fase 2
  (src/news_correlation_backtest.py), só depois de acumular dado real.

Uso:
  python3 src/news_collector.py
"""

from __future__ import annotations

import calendar
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

from news_sentiment import score_text
from news_sources import FEEDS, SYMBOL_ALIASES

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "news_radar.db"
LOG_FILE = DATA / "news_collector.log"

HTTP_TIMEOUT = 15
USER_AGENT = "crypto-radar-news-collector/1.0 (+paper-only research bot)"

_SYMBOL_PATTERNS: dict[str, list[re.Pattern]] = {
    symbol: [re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE) for alias in aliases]
    for symbol, aliases in SYMBOL_ALIASES.items()
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    line = f"[{utc_now_iso()}] {message}"
    print(line, flush=True)
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def get_connection() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_database(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guid TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            symbols_matched TEXT,
            sentiment_score REAL,
            sentiment_label TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_news_published_at "
        "ON news_items(published_at)"
    )
    conn.commit()


def match_symbols(title: str) -> list[str]:
    matched = []
    for symbol, patterns in _SYMBOL_PATTERNS.items():
        if any(p.search(title) for p in patterns):
            matched.append(symbol)
    return sorted(matched)


def parse_published(entry: dict) -> str:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        ts = calendar.timegm(struct)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return utc_now_iso()


def fetch_feed(session: requests.Session, feed: dict[str, str]):
    try:
        response = session.get(
            feed["url"],
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        log(f"AVISO: falha ao buscar {feed['name']} ({feed['url']}): {exc}")
        return []

    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        log(f"AVISO: feed {feed['name']} malformado sem entradas aproveitáveis.")
        return []

    return parsed.entries


def process_feed(conn: sqlite3.Connection, feed: dict[str, str]) -> tuple[int, int]:
    entries = fetch_feed(requests.Session(), feed)
    seen = 0
    inserted = 0

    for entry in entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        guid = entry.get("id") or entry.get("guid") or link

        if not title or not guid:
            continue

        seen += 1

        published_at = parse_published(entry)
        symbols_matched = match_symbols(title)
        score, label = score_text(title)

        try:
            conn.execute(
                """
                INSERT INTO news_items (
                    guid, source, title, link, published_at, fetched_at,
                    symbols_matched, sentiment_score, sentiment_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guid,
                    feed["name"],
                    title,
                    link,
                    published_at,
                    utc_now_iso(),
                    ",".join(symbols_matched),
                    score,
                    label,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # guid já existe - item já coletado antes, ignora.
            pass

    conn.commit()
    return seen, inserted


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - NEWS RADAR V1 -- COLETOR DE NOTÍCIAS")
    print("=" * 100)
    print(f"Banco:   {DB_PATH}")
    print(f"Feeds:   {len(FEEDS)}")
    print("Escopo:  somente coleta + sentimento léxico. Nenhuma ação de trading.")
    print("-" * 100)

    conn = get_connection()
    init_database(conn)

    total_seen = 0
    total_inserted = 0

    for feed in FEEDS:
        seen, inserted = process_feed(conn, feed)
        total_seen += seen
        total_inserted += inserted
        print(f"{feed['name']:<16} itens_no_feed={seen:<4} novos_gravados={inserted}")
        time.sleep(1)  # respeita os servidores dos feeds, sem pressa

    conn.close()

    print("-" * 100)
    print(f"Total no ciclo: {total_seen} itens vistos, {total_inserted} novos gravados.")
    print("=" * 100)

    log(f"CICLO concluído: vistos={total_seen} novos={total_inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
