#!/usr/bin/env python3
"""
CRYPTO RADAR - VARREDURA DE POEIRA (BINANCE LIVE, mainnet)

Roda 1x/dia via cron. Sobra de ativos que já tiveram a posição
fechada (troco de lote mínimo, taxa cobrada no próprio ativo, etc. -
ver memória do projeto) fica parada na carteira sem virar capital de
novo. Este script varre esse saldo e:

  1. Vende direto pra USDT o que já forma um lote válido no par
     ASSET/USDT (volta como capital de trade).
  2. O que é pequeno demais pra vender direto (abaixo do notional
     mínimo do par) vai pro endpoint nativo de "converter poeira em
     BNB" da própria Binance, feito exatamente pra esse caso.

Nunca toca ativo de posição aberta no momento (lido de
binance_live_open_positions.csv) nem USDT. BNB é tratado como
qualquer outro ativo, mas só o que passar de BNB_KEEP (reserva de
taxa, nunca vendida): se esse excedente formar lote válido, vende pra
USDT; se não formar, fica acumulando pro próximo dia (não dá pra
"converter BNB em BNB" no endpoint de poeira).
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from binance_live_executor import (  # noqa: E402
    ENV_FILE,
    OrderStateUnknown,
    build_exchange,
    load_env,
    log,
    place_market_order,
)

OPEN_POSITIONS_FILE = ROOT / "data" / "binance_live_open_positions.csv"
DUST_LOG = ROOT / "data" / "binance_live_dust_sweep.csv"

# BNB livre é a reserva que paga a taxa com desconto (ver
# BNB_RESERVE_MIN em binance_live_trader.py). Sem ela a taxa sai no
# próprio ativo e a venda arredonda abaixo de $5 (CRCLB ficou presa
# assim em 24/09). Só o que passar disto é tratado como sobra vendável.
BNB_KEEP = 0.005
DUST_LOG_FIELDS = [
    "timestamp", "asset", "action", "amount", "value_usdt_est", "ref",
]


def _open_bases() -> set[str]:
    if not OPEN_POSITIONS_FILE.exists():
        return set()
    with OPEN_POSITIONS_FILE.open(encoding="utf-8") as fh:
        return {row["symbol"].split("/")[0] for row in csv.DictReader(fh)}


def _append_dust_log(row: dict) -> None:
    is_new = not DUST_LOG.exists()
    DUST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DUST_LOG.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=DUST_LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def main() -> None:
    env = load_env(ENV_FILE)
    exchange = build_exchange(env)
    exchange.load_markets()

    balance = exchange.fetch_balance()
    open_bases = _open_bases()
    now = datetime.now(timezone.utc).isoformat()

    convert_candidates: list[str] = []

    for asset, total in balance.get("total", {}).items():
        if asset == "USDT" or asset in open_bases:
            continue
        free = float((balance.get(asset) or {}).get("free") or 0.0)
        if asset == "BNB":
            free = max(0.0, free - BNB_KEEP)
        if free <= 0:
            continue

        symbol = f"{asset}/USDT"
        market = exchange.markets.get(symbol)
        if not market:
            continue  # sem par direto com USDT - não força conversão às cegas

        try:
            price = float(exchange.fetch_ticker(symbol)["last"])
        except Exception as exc:
            log(f"[DUST] AVISO: não consegui cotar {symbol} ({exc}) - pulando por hoje.")
            continue

        value_usdt = free * price
        limits = market.get("limits", {})
        min_notional = limits.get("cost", {}).get("min")
        min_amount = limits.get("amount", {}).get("min")
        notional_ok = min_notional is None or value_usdt >= float(min_notional)
        amount_ok = min_amount is None or free >= float(min_amount)

        if notional_ok and amount_ok:
            try:
                quantity = float(exchange.amount_to_precision(symbol, free))
                if quantity <= 0:
                    continue
                order = place_market_order(exchange, symbol, "sell", quantity)
                filled = float(order.get("filled") or quantity)
                log(f"[DUST] Vendeu {filled} {asset} -> USDT (sobra de posição já fechada).")
                _append_dust_log({
                    "timestamp": now, "asset": asset, "action": "sell_usdt",
                    "amount": f"{filled:.12f}", "value_usdt_est": f"{value_usdt:.6f}",
                    "ref": order.get("id", ""),
                })
                # o step do par pode arredondar a venda pra baixo (ex.:
                # DOGE exige quantidade inteira) - o restinho que não
                # deu pra vender ainda pode virar BNB pela conversão
                # de poeira abaixo, no mesmo ciclo.
                leftover = free - filled
                if leftover > 0 and asset != "BNB":
                    convert_candidates.append(asset)
            except OrderStateUnknown as exc:
                log(f"[DUST] AVISO: estado da venda de {asset} incerto ({exc}) - conferir manualmente antes do próximo run.")
            except Exception as exc:
                log(f"[DUST] AVISO: venda direta de {asset} falhou ({type(exc).__name__}: {exc}).")
            continue

        if asset == "BNB":
            log(f"[DUST] BNB: sobra acima da reserva de {BNB_KEEP} BNB vale ${value_usdt:.4f}, ainda abaixo do lote mínimo (${float(min_notional or 0):.2f}) - acumulando pro próximo dia.")
            continue

        convert_candidates.append(asset)

    if convert_candidates:
        try:
            result = exchange.sapiPostAssetDust({"asset": convert_candidates})
            log(f"[DUST] Convertidos pra BNB via dust-transfer nativo da Binance: {convert_candidates}")
            _append_dust_log({
                "timestamp": now, "asset": ",".join(convert_candidates), "action": "convert_bnb",
                "amount": "", "value_usdt_est": "",
                "ref": str(result.get("transId", "")) if isinstance(result, dict) else "",
            })
        except Exception as exc:
            # Um ativo só (valor baixo demais até pro conversor de
            # poeira aceitar) derruba o lote inteiro - tenta de novo
            # um ativo por vez pra isolar o problemático.
            log(f"[DUST] AVISO: conversão em lote falhou ({type(exc).__name__}: {exc}) - tentando ativo por ativo.")
            for asset in convert_candidates:
                try:
                    result = exchange.sapiPostAssetDust({"asset": [asset]})
                    log(f"[DUST] Convertido pra BNB via dust-transfer nativo: {asset}")
                    _append_dust_log({
                        "timestamp": now, "asset": asset, "action": "convert_bnb",
                        "amount": "", "value_usdt_est": "",
                        "ref": str(result.get("transId", "")) if isinstance(result, dict) else "",
                    })
                except Exception as exc2:
                    log(f"[DUST] AVISO: {asset} não deu pra converter em BNB ({type(exc2).__name__}: {exc2}) - tenta de novo amanhã.")


if __name__ == "__main__":
    main()
