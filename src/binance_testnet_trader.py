#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE TESTNET TRADER

Liga os sinais LONG reais do scanner_v3 (via forward_signals.csv, a
mesma fonte que o paper trading v9 usa) ao Binance Spot Testnet -
ainda dinheiro fictício. Fecha o ciclo completo que o
binance_testnet_executor.py não fazia: sinal real -> ordem real no
testnet -> monitoramento por preço real -> saída por STOP/TARGET/TIME.

Isolado do paper trading v9 de propósito:
    - Lê forward_signals.csv (só leitura, nunca escreve nele).
    - Mantém posição/ledger PRÓPRIOS
      (data/binance_testnet_open_positions.csv,
      data/binance_testnet_trades.csv) - não compartilha estado com
      v9_17/v9_18/v9_21, então um mesmo sinal pode virar posição de
      paper trading E posição de testnet, são experimentos
      independentes.
    - STOP_PCT/TARGET_PCT/MAX_HOLD_HOURS importados de
      paper_trading_v9_17.py (mesma estratégia já validada em
      treino/teste - evita parâmetro duplicado divergindo, já
      aconteceu antes neste projeto).
    - Muitos símbolos exóticos que o scanner acompanha não existem no
      testnet (catálogo bem menor que o mainnet) - candidato que falha
      por BadSymbol é pulado, não aborta o ciclo inteiro.
    - entry_price/entry_time gravados no ledger do testnet são do
      PREENCHIMENTO REAL da ordem (não o preço do candle do sinal
      original, que é o que o paper trading v9 usa) - aqui a ordem é
      de verdade, então o preço real de execução é o dado que importa
      pra validar a engenharia.
    - TARGET (2026-08-31, pedido do usuário, experimental - não
      validado por treino/teste como o STOP/TARGET em si) virou trava
      de lucro: ao bater TARGET_PCT pela primeira vez não vende, só
      marca (campo target_reached na posição) e deixa correr enquanto
      o preço continuar subindo. Só sai por TARGET quando o retorno
      cair de volta abaixo de TARGET_PCT. Mesma regra em
      paper_trading_v9_17.py/v9_18.py.

PAPER real (v9) não é afetado. Ordem REAL (mainnet) nunca é enviada.
Sem cron - rodar manualmente:
    python3 src/binance_testnet_trader.py

O valor por posição é lido de data/binance_testnet_config.json a cada
ciclo (não é preciso reiniciar nada pra mudar) - o portal web
(web/testnet.php) escreve esse arquivo quando o usuário atualiza o
campo de valor.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from binance_testnet_executor import (
    ENV_FILE,
    LOG_FILE,
    build_exchange,
    call_with_retry,
    load_env,
    log,
)
from paper_trading_v9_17 import MAX_HOLD_HOURS, STOP_PCT, TARGET_PCT
from paper_trading_v9_21 import SIGNALS, is_fresh, parse_dt
from whatsapp_notify import send_whatsapp

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

TESTNET_OPEN_FILE = DATA / "binance_testnet_open_positions.csv"
TESTNET_LEDGER = DATA / "binance_testnet_trades.csv"

TESTNET_OPEN_FIELDS = [
    "signal_id", "symbol", "entry_time", "entry_price", "quantity",
    "entry_cost_usdt", "buy_order_id", "score", "confidence",
    "target_reached",
]
TESTNET_LEDGER_FIELDS = [
    "trade_id", "symbol", "entry_time", "exit_time", "entry_price",
    "exit_price", "quantity", "exit_reason", "gross_return_pct",
    "pnl_usdt", "buy_order_id", "sell_order_id",
]

CONFIG_FILE = DATA / "binance_testnet_config.json"

MAX_POSITIONS_TESTNET = 5
TESTNET_NOTIONAL_USDT = 15.0  # valor padrão, usado se o config.json não existir/for inválido


def load_notional_usdt() -> float:
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        value = float(raw["notional_usdt"])
        if value > 0:
            return value
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    return TESTNET_NOTIONAL_USDT


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    # Escreve num arquivo temporário e só troca com os.replace (atômico)
    # ao final - escrever direto no arquivo real (open "w") trunca o
    # conteúdo antes de gravar, então qualquer erro no meio do
    # writerows (ex: linha com campo que não existe em `fields`, já
    # aconteceu de verdade) apaga o arquivo em vez de só falhar.
    # extrasaction="ignore" evita esse erro específico de schema
    # divergente entre código e dado.
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def append_csv(path: Path, fields: list[str], row: dict) -> None:
    if path.exists():
        with path.open("r", newline="", encoding="utf-8") as fh:
            current_header = next(csv.reader(fh), [])
        if current_header and current_header != fields:
            # Schema mudou (ex: campo novo) - reescreve o arquivo inteiro
            # com o header atual, preenchendo linhas antigas com "" nos
            # campos que não existiam antes, em vez de desalinhar colunas.
            write_csv(path, fields, read_csv(path))

    is_new = not path.exists()
    DATA.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def testnet_open_ids(open_rows: list[dict]) -> set[str]:
    return {r["signal_id"].strip() for r in open_rows if r.get("signal_id")}


def testnet_closed_ids(ledger_rows: list[dict]) -> set[str]:
    result = set()
    for r in ledger_rows:
        tid = r.get("trade_id", "").strip()
        if tid:
            result.add(tid.rsplit("_", 1)[0])
    return result


def best_actionable_per_symbol(
    open_ids: set[str], closed_ids: set[str]
) -> dict[str, dict]:
    """Mesmo critério do preflight/executor do v9: LONG, fresco, não
    aberto/fechado, e só o sinal mais recente por símbolo."""
    rows = read_csv(SIGNALS)
    best: dict[str, dict] = {}
    for row in rows:
        sid = row.get("signal_id", "").strip()
        if not sid or sid in open_ids or sid in closed_ids:
            continue
        if row.get("signal", "").strip().upper() != "LONG":
            continue
        if not is_fresh(row.get("entry_time", "")):
            continue
        sym = row["symbol"].strip().upper()
        current = best.get(sym)
        if current is None or parse_dt(row["entry_time"]) > parse_dt(
            current["entry_time"]
        ):
            best[sym] = row
    return best


def monitor_open_positions(exchange) -> tuple[list[dict], int]:
    remaining = []
    closed_now = 0
    for pos in read_csv(TESTNET_OPEN_FILE):
        symbol = pos["symbol"]
        try:
            ticker = call_with_retry(exchange.fetch_ticker, symbol)
            price = ticker["last"]
        except Exception as exc:
            log(f"AVISO monitor {symbol}: {type(exc).__name__}: {exc}")
            remaining.append(pos)
            continue

        entry = float(pos["entry_price"])
        change = price / entry - 1.0
        opened = parse_dt(pos["entry_time"])
        age_hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0
        target_reached = (pos.get("target_reached") or "0").strip() == "1"

        # Trava de lucro (2026-08-31, pedido do usuário - experimental,
        # não validado por treino/teste como o STOP/TARGET em si): ao
        # bater TARGET pela primeira vez, não vende - só marca
        # target_reached e deixa correr. Só sai por TARGET quando o
        # retorno cair de volta abaixo de TARGET_PCT (ou por STOP/TIME
        # antes de bater o alvo, ou por TIME depois).
        reason = None
        if not target_reached:
            if change <= -STOP_PCT:
                reason = "STOP"
            elif age_hours >= MAX_HOLD_HOURS:
                reason = "TIME"
            elif change >= TARGET_PCT:
                target_reached = True
        else:
            if age_hours >= MAX_HOLD_HOURS:
                reason = "TIME"
            elif change < TARGET_PCT:
                reason = "TARGET"

        if not reason:
            pos["target_reached"] = "1" if target_reached else "0"
            remaining.append(pos)
            continue

        try:
            quantity = float(exchange.amount_to_precision(symbol, float(pos["quantity"])))
            sell_order = call_with_retry(
                exchange.create_order, symbol, "market", "sell", quantity
            )
        except Exception as exc:
            log(
                f"AVISO: {symbol} bateu {reason} mas venda de fechamento "
                f"falhou ({type(exc).__name__}: {exc}) - mantendo posição "
                "aberta pra tentar de novo no próximo ciclo."
            )
            remaining.append(pos)
            continue

        fill_price = sell_order.get("average") or sell_order.get("price") or price
        gross_return_pct = (float(fill_price) / entry - 1.0) * 100.0
        exit_time = datetime.now(timezone.utc).isoformat()

        # entry_cost_usdt só existe em posições abertas depois desta versão -
        # posição antiga (sem o campo) cai no fallback preço*quantidade.
        entry_cost = pos.get("entry_cost_usdt", "").strip()
        entry_cost_usdt = float(entry_cost) if entry_cost else entry * quantity
        exit_cost_usdt = float(
            sell_order.get("cost") or (float(fill_price) * quantity)
        )
        pnl_usdt = exit_cost_usdt - entry_cost_usdt

        append_csv(TESTNET_LEDGER, TESTNET_LEDGER_FIELDS, {
            "trade_id": f"{pos['signal_id']}_{exit_time}",
            "symbol": symbol,
            "entry_time": pos["entry_time"],
            "exit_time": exit_time,
            "entry_price": pos["entry_price"],
            "exit_price": f"{float(fill_price):.12f}",
            "quantity": pos["quantity"],
            "exit_reason": reason,
            "gross_return_pct": f"{gross_return_pct:.6f}",
            "pnl_usdt": f"{pnl_usdt:.6f}",
            "buy_order_id": pos.get("buy_order_id", ""),
            "sell_order_id": sell_order.get("id", ""),
        })
        log(
            f"CLOSE {symbol:12s} {reason:6s} "
            f"gross={gross_return_pct:+.4f}% pnl=${pnl_usdt:+.4f} "
            f"sell_order={sell_order.get('id')}"
        )
        send_whatsapp(
            f"[Testnet] {symbol} fechado por {reason}: "
            f"{gross_return_pct:+.2f}% (${pnl_usdt:+.2f} fictício)"
        )
        closed_now += 1

    return remaining, closed_now


def open_new_positions(
    exchange, remaining: list[dict], notional_usdt: float
) -> list[dict]:
    slots = max(0, MAX_POSITIONS_TESTNET - len(remaining))
    if slots <= 0:
        return remaining

    open_rows = read_csv(TESTNET_OPEN_FILE)
    ledger_rows = read_csv(TESTNET_LEDGER)
    open_ids = testnet_open_ids(open_rows)
    closed_ids = testnet_closed_ids(ledger_rows)
    open_symbols = {p["symbol"].strip().upper() for p in remaining}

    candidates = best_actionable_per_symbol(open_ids, closed_ids)

    for sym, signal in candidates.items():
        if slots <= 0:
            break
        if sym in open_symbols:
            continue

        try:
            ticker = call_with_retry(exchange.fetch_ticker, sym)
            price = ticker["last"]
            raw_amount = notional_usdt / price
            amount = float(exchange.amount_to_precision(sym, raw_amount))
            buy_order = call_with_retry(
                exchange.create_order, sym, "market", "buy", amount
            )
        except ccxt.BadSymbol:
            continue
        except Exception as exc:
            log(f"AVISO abertura {sym}: {type(exc).__name__}: {exc}")
            continue

        filled = float(buy_order.get("filled") or 0.0)
        if filled <= 0:
            log(f"AVISO {sym}: ordem de compra não preencheu, ignorando.")
            continue

        fill_price = buy_order.get("average") or buy_order.get("price") or price
        entry_cost_usdt = float(buy_order.get("cost") or (float(fill_price) * filled))
        entry_time = datetime.now(timezone.utc).isoformat()

        remaining.append({
            "signal_id": signal["signal_id"],
            "symbol": sym,
            "entry_time": entry_time,
            "entry_price": f"{float(fill_price):.12f}",
            "quantity": f"{filled:.12f}",
            "entry_cost_usdt": f"{entry_cost_usdt:.6f}",
            "buy_order_id": str(buy_order.get("id", "")),
            "score": signal.get("score", ""),
            "confidence": signal.get("confidence", ""),
            "target_reached": "0",
        })
        open_symbols.add(sym)
        slots -= 1
        log(
            f"OPEN  {sym:12s} entry={fill_price} qty={filled} "
            f"buy_order={buy_order.get('id')}"
        )

    return remaining


def run_cycle(exchange) -> tuple[int, int]:
    """Um ciclo completo: monitora/fecha posições, tenta abrir novas
    com o notional atual do config.json. Usado tanto pelo modo manual
    (main) quanto pelo loop contínuo (binance_testnet_loop.py)."""
    notional_usdt = load_notional_usdt()
    remaining, closed_now = monitor_open_positions(exchange)
    remaining = open_new_positions(exchange, remaining, notional_usdt)
    write_csv(TESTNET_OPEN_FILE, TESTNET_OPEN_FIELDS, remaining)
    return closed_now, len(remaining)


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - BINANCE TESTNET TRADER")
    print("=" * 100)
    print("Ambiente: BINANCE SPOT TESTNET (testnet.binance.vision)")
    print("Dinheiro real: NÃO - saldo fictício, ambiente separado do mainnet")
    print(f"Sinais: {SIGNALS}")
    print(f"STOP / TARGET / MAX_HOLD: {STOP_PCT:.2%} / {TARGET_PCT:.2%} / {MAX_HOLD_HOURS}h")
    print(f"Notional por posição: ${load_notional_usdt():.2f} | Máx. posições: {MAX_POSITIONS_TESTNET}")
    print("-" * 100)

    try:
        env = load_env(ENV_FILE)
        exchange = build_exchange(env)
        exchange.load_markets()
    except Exception as exc:
        log(f"ERRO de configuração: {exc}")
        return 1

    closed_now, open_count = run_cycle(exchange)

    log(
        f"CICLO concluído: {closed_now} fechada(s), "
        f"{open_count} posição(ões) aberta(s) no testnet."
    )
    print("=" * 100)
    print("Nenhuma ordem real foi enviada.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
