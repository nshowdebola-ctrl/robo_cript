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
binance_live_open_positions.csv) nem USDT. BNB fica por último:
depois da conversão de poeira (que gera BNB), o que passar de BNB_KEEP
(reserva de taxa, nunca vendida) é vendido pra USDT se formar lote
válido; se não formar, fica acumulando pro próximo dia.
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
BNB_KEEP = 0.002
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
        if asset == "BNB":
            continue  # tratado em _sell_bnb_excess, depois da conversão de poeira
        free = float((balance.get(asset) or {}).get("free") or 0.0)
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
                if leftover > 0:
                    convert_candidates.append(asset)
            except OrderStateUnknown as exc:
                log(f"[DUST] AVISO: estado da venda de {asset} incerto ({exc}) - conferir manualmente antes do próximo run.")
            except Exception as exc:
                log(f"[DUST] AVISO: venda direta de {asset} falhou ({type(exc).__name__}: {exc}).")
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

    _sell_bnb_excess(exchange, now)


def _open_bnb_quantity() -> float:
    if not OPEN_POSITIONS_FILE.exists():
        return 0.0
    with OPEN_POSITIONS_FILE.open(encoding="utf-8") as fh:
        return sum(
            float(row.get("quantity") or 0.0)
            for row in csv.DictReader(fh)
            if row["symbol"].split("/")[0] == "BNB"
        )


def _sell_bnb_excess(exchange, now: str) -> None:
    """Vende pra USDT o BNB acima de BNB_KEEP, se formar lote válido.
    Roda depois da conversão de poeira pra já contar o BNB que ela gerou
    (saldo relido da Binance)."""
    symbol = "BNB/USDT"
    try:
        free = float((exchange.fetch_balance().get("BNB") or {}).get("free") or 0.0)
        price = float(exchange.fetch_ticker(symbol)["last"])
    except Exception as exc:
        log(f"[DUST] AVISO: não consegui ler saldo/cotação de BNB ({exc}) - pulando por hoje.")
        return
    # BNB que é posição aberta do robô (sinal BNB/USDT) não é excedente.
    excess = free - BNB_KEEP - _open_bnb_quantity()
    if excess <= 0:
        return
    value_usdt = excess * price
    min_notional = exchange.markets[symbol].get("limits", {}).get("cost", {}).get("min") or 0.0
    quantity = float(exchange.amount_to_precision(symbol, excess))
    if quantity <= 0 or quantity * price < float(min_notional):
        log(
            f"[DUST] BNB: excedente acima da reserva de {BNB_KEEP} BNB é {excess:.6f} "
            f"(${value_usdt:.2f}); arredondado ao passo do par dá {quantity} BNB = "
            f"${quantity * price:.2f}, abaixo do lote mínimo (${float(min_notional):.2f}) - "
            "acumulando pro próximo dia."
        )
        return
    try:
        order = place_market_order(exchange, symbol, "sell", quantity)
    except OrderStateUnknown as exc:
        log(f"[DUST] AVISO: estado da venda de BNB incerto ({exc}) - conferir manualmente antes do próximo run.")
        return
    except Exception as exc:
        log(f"[DUST] AVISO: venda do excedente de BNB falhou ({type(exc).__name__}: {exc}).")
        return
    filled = float(order.get("filled") or quantity)
    log(f"[DUST] Vendeu {filled} BNB -> USDT (excedente acima da reserva de {BNB_KEEP} BNB).")
    _append_dust_log({
        "timestamp": now, "asset": "BNB", "action": "sell_usdt",
        "amount": f"{filled:.12f}", "value_usdt_est": f"{value_usdt:.6f}",
        "ref": order.get("id", ""),
    })


if __name__ == "__main__":
    main()
