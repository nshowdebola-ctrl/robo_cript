#!/usr/bin/env python3
"""
CRYPTO RADAR - LISTA SOBRAS NA CARTEIRA LIVE (só leitura)

Mostra os ativos com saldo na conta Binance live que NÃO são posição
aberta do robô (sobra de lote/taxa, poeira, BNB da taxa), com o valor
em USDT e se já dá pra vender direto (>= notional mínimo do par) ou só
converter em BNB. Não envia ordem nenhuma - a venda/conversão continua
sendo do binance_live_dust_sweeper.py (cron diário).

Uso:
  python3 src/binance_live_leftovers.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from binance_live_dust_sweeper import BNB_KEEP  # noqa: E402
from binance_live_executor import ENV_FILE, build_exchange, load_env  # noqa: E402

OPEN_FILE = ROOT / "data" / "binance_live_open_positions.csv"
IGNORE = {"USDT"}


def open_positions() -> dict[str, float]:
    with open(OPEN_FILE, newline="", encoding="utf-8") as f:
        return {
            r["symbol"].split("/")[0]: float(r["quantity"])
            for r in csv.DictReader(f)
        }


def main() -> int:
    exchange = build_exchange(load_env(ENV_FILE))
    exchange.load_markets()
    balance = exchange.fetch_balance()
    positions = open_positions()

    usdt = balance.get("USDT", {})
    print(f"USDT livre: {usdt.get('free', 0):.2f} | em ordem: {usdt.get('used', 0):.2f}")
    print()
    print(f"{'ativo':8s} {'saldo':>16s} {'posição robô':>14s} {'sobra':>16s} {'sobra $':>9s}  situação")

    total_leftover = 0.0
    for asset, amounts in sorted(balance["total"].items()):
        if asset in IGNORE or not amounts:
            continue
        pair = f"{asset}/USDT"
        tracked = positions.get(asset, 0.0)
        leftover = amounts - tracked
        price = None
        if pair in exchange.markets:
            try:
                price = float(exchange.fetch_ticker(pair)["last"])
            except Exception:
                price = None
        value = leftover * price if price else None
        if value is not None and abs(value) < 0.0001:
            continue

        if pair not in exchange.markets:
            status = "sem par USDT"
        elif asset.startswith("LD"):
            status = "Earn (Simple Earn)"
        elif leftover <= 0:
            status = "só posição aberta"
        else:
            min_cost = (exchange.markets[pair].get("limits", {}).get("cost", {}) or {}).get("min") or 5.0
            if asset == "BNB":
                excess = (leftover - BNB_KEEP) * price if price else 0.0
                status = (
                    f"reserva {BNB_KEEP} + excedente ${max(0.0, excess):.2f}"
                    + (" (vendável)" if excess >= min_cost else " (< lote mínimo)")
                )
            elif value is not None and value >= min_cost:
                status = f"VENDÁVEL (>= ${min_cost:.0f})"
            else:
                status = "poeira -> BNB no sweeper"
        if value is not None and leftover > 0:
            total_leftover += value
        print(
            f"{asset:8s} {amounts:16.8f} {tracked:14.8f} {leftover:16.8f} "
            f"{(f'{value:.4f}' if value is not None else '-'):>9s}  {status}"
        )

    print()
    print(f"Total em sobras (fora das posições abertas): ${total_leftover:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
