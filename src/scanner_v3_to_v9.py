#!/usr/bin/env python3
"""
CRYPTO RADAR - V9.20
Adaptador oficial: Scanner V3 -> forward_signals.csv

Objetivo:
    Ler somente sinais já produzidos pelo scanner_v3.py na tabela
    scanner_v3_results e publicar novos sinais no formato esperado
    pelo pipeline V9.

Princípios:
    - NÃO altera scanner_v3.py.
    - NÃO lê o CSV legado V8 para criar sinais.
    - NÃO inventa preço, score, confiança ou timestamp.
    - NÃO cria dados financeiros.
    - Somente sinais COMPRA / COMPRA FORTE são convertidos para LONG.
    - Duplicatas são evitadas pelo signal_id.
    - Um símbolo que já tem sinal LONG pendente (acionável: não expirado,
      não aberto, não fechado) não recebe sinal novo - o score do
      scanner_v3.py é recalculado do zero a cada hora, sem memória, então
      uma moeda em tendência longa reapareceria como "sinal novo" todo
      ciclo e inflaria a fila com dezenas de entradas redundantes pro
      mesmo símbolo (já aconteceu: 55 símbolos geraram 500 sinais
      "acionáveis" em ~2 dias, travando o executor).
    - Processa somente a rodada mais recente do Scanner V3.
"""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

from paper_trading_v9_21 import ids_from_ledger, ids_from_open, is_fresh


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"

DB_PATH = DATA_DIR / "crypto_radar.db"
OUTPUT_PATH = DATA_DIR / "forward_signals.csv"

TIMEFRAME_EXPECTED = "1h"

OUTPUT_FIELDS = [
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


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_output() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not OUTPUT_PATH.exists() or OUTPUT_PATH.stat().st_size == 0:
        with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()


def read_existing_rows() -> list[dict]:
    if not OUTPUT_PATH.exists():
        return []

    with OUTPUT_PATH.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_existing_ids(rows: list[dict]) -> set[str]:
    return {
        (row.get("signal_id") or "").strip()
        for row in rows
        if (row.get("signal_id") or "").strip()
    }


def pending_symbols(rows: list[dict]) -> set[str]:
    """Símbolos com sinal LONG já acionável na fila (não expirado, não
    aberto, não fechado) - reemitir sinal novo pra um desses símbolos
    seria a mesma oportunidade duplicada, não uma entrada nova."""
    open_ids = ids_from_open()
    closed_ids = ids_from_ledger()
    pending = set()
    for row in rows:
        sid = (row.get("signal_id") or "").strip()
        if not sid or sid in open_ids or sid in closed_ids:
            continue
        if (row.get("signal") or "").strip().upper() != "LONG":
            continue
        if not is_fresh(row.get("entry_time", "")):
            continue
        pending.add((row.get("symbol") or "").strip().upper())
    return pending


def latest_run(conn: sqlite3.Connection) -> str | None:
    # run_at identifica a EXECUÇÃO do scanner (horário real em que rodou),
    # diferente de "timestamp" (horário do candle analisado). Duas
    # execuções dentro da mesma hora podem analisar o mesmo candle ainda
    # não fechado na vela seguinte; usar "timestamp" para achar "a última
    # rodada" misturava execuções diferentes que caíssem no mesmo candle,
    # gerando sinais duplicados/reprocessados. run_at é único por execução.
    row = conn.execute(
        "SELECT MAX(run_at) FROM scanner_v3_results"
    ).fetchone()
    return row[0] if row and row[0] else None


def load_latest_buy_signals(
    conn: sqlite3.Connection,
) -> tuple[str | None, list[dict]]:
    run_at = latest_run(conn)

    if not run_at:
        return None, []

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(scanner_v3_results)"
        ).fetchall()
    }

    required = {
        "run_at",
        "timestamp",
        "symbol",
        "timeframe",
        "price",
        "score",
        "signal",
        "confidence",
    }

    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(
            "Schema scanner_v3_results sem campos obrigatórios: "
            + ", ".join(missing)
        )

    rows = conn.execute(
        """
        SELECT
            timestamp,
            symbol,
            timeframe,
            price,
            score,
            signal,
            confidence
        FROM scanner_v3_results
        WHERE run_at = ?
          AND timeframe = ?
          AND signal IN ('COMPRA', 'COMPRA FORTE')
        ORDER BY score DESC, confidence DESC, symbol ASC
        """,
        (run_at, TIMEFRAME_EXPECTED),
    ).fetchall()

    return run_at, [
        {
            "timestamp": r[0],
            "symbol": r[1],
            "timeframe": r[2],
            "price": r[3],
            "score": r[4],
            "signal": r[5],
            "confidence": r[6],
        }
        for r in rows
    ]


def make_signal_id(row: dict) -> str:
    """
    ID determinístico para o par (timestamp, símbolo, cenário).
    O hash evita IDs excessivamente longos e mantém estabilidade
    entre execuções do adaptador.
    """
    raw = (
        f"{row['timestamp']}|"
        f"{row['symbol']}|"
        f"{row['timeframe']}|"
        f"{row['signal']}"
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    compact_ts = (
        row["timestamp"]
        .replace("-", "")
        .replace(":", "")
        .replace("T", "")
        .replace("+00:00", "")
        .replace("Z", "")
    )
    return f"{compact_ts}_{digest}"


def convert(row: dict) -> dict:
    return {
        "signal_id": make_signal_id(row),
        "scenario": "V9.20_V3_FORWARD",
        "symbol": row["symbol"],
        "entry_time": row["timestamp"],
        "entry_price": f"{float(row['price']):.12f}",
        "timeframe": row["timeframe"],
        "score": f"{float(row['score']):.2f}",
        "confidence": f"{float(row['confidence']):.2f}",
        "signal": "LONG",
    }


def append_new(
    rows: list[dict], existing_ids: set[str], pending: set[str]
) -> tuple[int, int]:
    new_rows = []
    skipped_pending = 0
    blocked_symbols = set(pending)
    for row in rows:
        if row["signal_id"] in existing_ids:
            continue
        symbol = row["symbol"].strip().upper()
        if symbol in blocked_symbols:
            skipped_pending += 1
            continue
        new_rows.append(row)
        # Também evita duas linhas novas pro mesmo símbolo na mesma rodada.
        blocked_symbols.add(symbol)

    if new_rows:
        with OUTPUT_PATH.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=OUTPUT_FIELDS,
                lineterminator="\n",
            )
            writer.writerows(new_rows)

    return len(new_rows), skipped_pending


def main() -> int:
    print("=" * 90)
    print("CRYPTO RADAR - PAPER TRADING V9.20 -- V3 -> FORWARD SIGNALS")
    print("=" * 90)
    print(f"Banco V3:       {DB_PATH}")
    print(f"Saída V9:       {OUTPUT_PATH}")
    print("Modo:           PAPER ONLY")
    print("Ordens reais:   NÃO")
    print("CSV legado V8:  NÃO UTILIZADO")
    print("-" * 90)

    if not DB_PATH.exists():
        print("ERRO: banco crypto_radar.db não encontrado.")
        return 1

    ensure_output()
    existing_rows = read_existing_rows()
    existing_ids = read_existing_ids(existing_rows)
    pending = pending_symbols(existing_rows)

    conn = None
    try:
        conn = connect_db()
        ts, source_rows = load_latest_buy_signals(conn)
    except Exception as exc:
        print(f"ERRO ao ler V3: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if conn is not None:
            conn.close()

    if ts is None:
        print("Nenhuma rodada V3 encontrada.")
        return 0

    converted = [convert(row) for row in source_rows]
    added, skipped_pending = append_new(converted, existing_ids, pending)
    already_existing = len(source_rows) - added - skipped_pending

    print(f"Última rodada V3: {ts}")
    print(f"Sinais COMPRA/COMPRA FORTE:              {len(source_rows)}")
    print(f"Sinais novos gravados:                   {added}")
    print(f"Sinais já existentes:                    {already_existing}")
    print(f"Símbolo já com sinal pendente (ignorados): {skipped_pending}")
    print()
    print("IMPORTANTE:")
    print("  O preço, timestamp, score e confiança vêm diretamente do V3.")
    print("  O adaptador não cria fees, quantity, notional ou P&L.")
    print("  LONG é somente a tradução de COMPRA/COMPRA FORTE para o schema V9.")
    print()
    print("Próximo fluxo:")
    print("  scanner_v3.py -> SQLite -> V9.20 -> forward_signals.csv -> V9.15/V9.17")
    print("=" * 90)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
