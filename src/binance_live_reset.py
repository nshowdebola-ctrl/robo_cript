#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE LIVE RESET (mainnet, DINHEIRO REAL) - "vender tudo"

Paralelo de binance_testnet_reset.py, com duas diferenças deliberadas
por ser dinheiro real (achados de revisão de código, 2026-09-05):

1. Vende só a QUANTIDADE que o bot registra em cada posição aberta
   (data/binance_live_open_positions.csv), nunca o saldo livre inteiro
   do ativo na conta - a versão anterior lia `balance[base]['free']` e
   vendia tudo, o que liquidaria saldo real que o usuário tenha na
   conta por outro motivo (ex: BTC comprado fora do bot) e que o bot
   nunca rastreou como posição própria.

2. NÃO apaga data/binance_live_trades.csv. O ledger é a única fonte
   que binance_live_circuit_breaker.compute_drawdown_pct() soma pra
   calcular a perda acumulada - zerá-lo apagaria silenciosamente o
   sinal de perda que o circuit breaker depende, mesmo a perda real em
   dinheiro não tendo mudado. Histórico de trades fica preservado;
   só a lista de posições abertas é limpa (libera os slots).

NÃO mexe em data/binance_live_circuit_breaker_state.json - "vender
tudo" e "reativar circuit breaker" ficam sempre separados (decisão
confirmada com o usuário em 2026-09-05): se o breaker estiver travado,
continua travado depois do reset, até uma ação manual própria.

Chamado pelo portal (web/live.php, botão "Vender tudo") ou
manualmente:
    python3 src/binance_live_reset.py

O loop (binance_live_loop.py) deve estar PARADO antes de rodar isso -
o portal já garante isso (para o loop e confirma que encerrou antes de
chamar, ver web/live.php stopLoop()).
"""

from __future__ import annotations

from binance_live_executor import ENV_FILE, build_exchange, load_env, log
from binance_live_trader import LIVE_OPEN_FIELDS, LIVE_OPEN_FILE
from binance_testnet_trader import read_csv, write_csv


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - BINANCE LIVE RESET (DINHEIRO REAL)")
    print("=" * 100)

    positions = read_csv(LIVE_OPEN_FILE)
    qty_by_symbol: dict[str, float] = {}
    for pos in positions:
        symbol = (pos.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            qty = float(pos.get("quantity") or 0.0)
        except ValueError:
            continue
        qty_by_symbol[symbol] = qty_by_symbol.get(symbol, 0.0) + qty

    if qty_by_symbol:
        try:
            env = load_env(ENV_FILE)
            exchange = build_exchange(env)
            exchange.load_markets()
            balance = exchange.fetch_balance()
        except Exception as exc:
            log(f"[LIVE] RESET: ERRO ao conectar, não vou vender nada: {exc}")
            return 1

        for symbol in sorted(qty_by_symbol):
            base = symbol.split("/")[0]
            free = balance.get(base, {}).get("free", 0.0) or 0.0
            # Nunca vende mais do que o bot registrou como próprio, e
            # nunca mais do que o saldo livre real (a diferença pode
            # existir por arredondamento/taxa) - o menor dos dois.
            amount = min(qty_by_symbol[symbol], free)
            if not amount or amount <= 0:
                log(f"[LIVE] RESET: {symbol} sem saldo livre suficiente pra vender, pulando.")
                continue
            try:
                precise = float(exchange.amount_to_precision(symbol, amount))
                order = exchange.create_order(symbol, "market", "sell", precise)
                log(f"[LIVE] RESET: vendido {precise} {symbol} (cost={order.get('cost')})")
            except Exception as exc:
                log(f"[LIVE] RESET: ERRO ao vender {symbol}: {type(exc).__name__}: {exc}")
    else:
        log("[LIVE] RESET: nenhuma posição aberta registrada, nada pra vender.")

    write_csv(LIVE_OPEN_FILE, LIVE_OPEN_FIELDS, [])

    log(
        "[LIVE] RESET: posições abertas zeradas. Ledger de trades e "
        "circuit breaker preservados (não alterados por este reset)."
    )
    print("=" * 100)
    print("Concluído.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
