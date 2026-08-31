#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE TESTNET RESET

Zera o estado do binance_testnet_trader.py: vende de volta pra USDT
tudo que estiver registrado como posição aberta (data/
binance_testnet_open_positions.csv) e apaga o histórico de posições
abertas/trades fechados, mantendo só o cabeçalho dos CSVs.

NÃO mexe no saldo "de fábrica" da conta testnet (a Binance Spot
Testnet já credita um catálogo enorme de ativos por padrão em toda
conta nova - não é nada que o bot comprou, não faz sentido tentar
"zerar" isso). Só vende os símbolos que o bot tem registrados como
posição aberta agora.

Chamado pelo portal web (web/testnet.php, botão "Zerar tudo") ou
manualmente:
    python3 src/binance_testnet_reset.py

O loop (binance_testnet_loop.py) deve estar PARADO antes de rodar isso
- rodar com o loop ativo pode fazer os dois mexerem no mesmo CSV ao
mesmo tempo. O portal já garante isso (para o loop antes de chamar).
"""

from __future__ import annotations

import csv

from binance_testnet_executor import ENV_FILE, build_exchange, load_env, log
from binance_testnet_trader import (
    TESTNET_LEDGER,
    TESTNET_LEDGER_FIELDS,
    TESTNET_OPEN_FIELDS,
    TESTNET_OPEN_FILE,
    read_csv,
    write_csv,
)


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - BINANCE TESTNET RESET")
    print("=" * 100)

    positions = read_csv(TESTNET_OPEN_FILE)
    symbols = sorted({p["symbol"].strip().upper() for p in positions if p.get("symbol")})

    if symbols:
        try:
            env = load_env(ENV_FILE)
            exchange = build_exchange(env)
            exchange.load_markets()
            balance = exchange.fetch_balance()
        except Exception as exc:
            log(f"RESET: ERRO ao conectar na testnet, não vou vender nada: {exc}")
            return 1

        for symbol in symbols:
            base = symbol.split("/")[0]
            amount = balance.get(base, {}).get("free", 0.0)
            if not amount or amount <= 0:
                log(f"RESET: {symbol} sem saldo pra vender, pulando.")
                continue
            try:
                precise = float(exchange.amount_to_precision(symbol, amount))
                order = exchange.create_order(symbol, "market", "sell", precise)
                log(f"RESET: vendido {precise} {symbol} (cost={order.get('cost')})")
            except Exception as exc:
                log(f"RESET: ERRO ao vender {symbol}: {type(exc).__name__}: {exc}")
    else:
        log("RESET: nenhuma posição aberta registrada, nada pra vender.")

    write_csv(TESTNET_OPEN_FILE, TESTNET_OPEN_FIELDS, [])

    with TESTNET_LEDGER.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TESTNET_LEDGER_FIELDS, lineterminator="\n")
        writer.writeheader()

    log("RESET: posições e ledger do testnet zerados.")
    print("=" * 100)
    print("Concluído.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
