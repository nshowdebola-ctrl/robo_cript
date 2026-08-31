#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE TESTNET EXECUTOR

Objetivo: validar a ENGENHARIA de envio de ordem contra o Binance Spot
Testnet (testnet.binance.vision - dado de mercado real, dinheiro
fictício, ambiente separado do mainnet). NÃO valida se a estratégia dá
lucro - isso continua sendo medido pelo paper trading (v9_21), que usa
dado real de mercado sem custo de engenharia de exchange nenhum.

Escopo desta primeira versão:
    1) autenticar com a API key do testnet (fetch_balance);
    2) comprar um valor pequeno e fixo de um par líquido (mercado);
    3) confirmar a execução da ordem;
    4) vender de volta pra USDT (fecha o ciclo, não deixa posição aberta);
    5) tratar erro de rede/rate limit com retry, e erro de exchange
       (saldo insuficiente, ordem inválida) sem retry - falha visível.

Isolado de propósito do pipeline de produção (paper_trading_v9_21.py):
script separado, sem cron, sem tocar em forward_signals.csv nem no
ledger v9. Rodar manualmente:
    python3 src/binance_testnet_executor.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".binance-testnet.env"
LOG_FILE = ROOT / "data" / "binance_testnet.log"

SYMBOL = "BTC/USDT"
TEST_NOTIONAL_USDT = 15.0  # acima do minNotional típico de spot ($10)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} não encontrado - crie com BINANCE_TESTNET_API_KEY "
            "e BINANCE_TESTNET_API_SECRET."
        )
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def build_exchange(env: dict[str, str]) -> ccxt.binance:
    api_key = env.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = env.get("BINANCE_TESTNET_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError(
            "BINANCE_TESTNET_API_KEY/BINANCE_TESTNET_API_SECRET ausentes "
            f"em {ENV_FILE}."
        )

    exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    exchange.set_sandbox_mode(True)
    return exchange


def call_with_retry(fn, *args, **kwargs):
    """Retry com backoff só pra falha transiente (rede/rate limit).
    Erro de exchange (saldo insuficiente, símbolo inválido, etc.) não é
    transiente - propaga na hora, retry não vai resolver."""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except (ccxt.NetworkError, ccxt.RateLimitExceeded, ccxt.DDoSProtection) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF_SECONDS * attempt
            log(
                f"AVISO: {type(exc).__name__} na tentativa {attempt}/"
                f"{MAX_RETRIES} - retry em {wait:.0f}s. Detalhe: {exc}"
            )
            time.sleep(wait)
    raise RuntimeError(
        f"Falhou após {MAX_RETRIES} tentativas: {last_exc}"
    ) from last_exc


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - BINANCE TESTNET EXECUTOR")
    print("=" * 100)
    print("Ambiente: BINANCE SPOT TESTNET (testnet.binance.vision)")
    print("Dinheiro real: NÃO - saldo fictício, ambiente separado do mainnet")
    print(f"Par de teste: {SYMBOL}")
    print(f"Notional de teste: ${TEST_NOTIONAL_USDT:.2f}")
    print("-" * 100)

    try:
        env = load_env(ENV_FILE)
        exchange = build_exchange(env)
    except Exception as exc:
        log(f"ERRO de configuração: {exc}")
        return 1

    # 1. Autenticação.
    try:
        balance = call_with_retry(exchange.fetch_balance)
    except ccxt.AuthenticationError as exc:
        log(f"ERRO de autenticação: {exc}")
        return 1
    except Exception as exc:
        log(f"ERRO ao autenticar: {type(exc).__name__}: {exc}")
        return 1

    usdt_free = balance.get("USDT", {}).get("free", 0.0)
    log(f"AUTENTICADO. Saldo USDT livre (testnet): {usdt_free}")

    # 2. Preço atual e tamanho da ordem.
    try:
        exchange.load_markets()
        ticker = call_with_retry(exchange.fetch_ticker, SYMBOL)
        price = ticker["last"]
        raw_amount = TEST_NOTIONAL_USDT / price
        amount = float(exchange.amount_to_precision(SYMBOL, raw_amount))
    except Exception as exc:
        log(f"ERRO ao calcular ordem: {type(exc).__name__}: {exc}")
        return 1

    log(f"Preço atual {SYMBOL}: {price} | quantidade calculada: {amount}")

    # 3. Ordem de compra a mercado.
    try:
        buy_order = call_with_retry(
            exchange.create_order, SYMBOL, "market", "buy", amount
        )
    except ccxt.InsufficientFunds as exc:
        log(f"ERRO: saldo insuficiente na testnet: {exc}")
        return 1
    except ccxt.InvalidOrder as exc:
        log(f"ERRO: ordem inválida (checar minNotional/precisão): {exc}")
        return 1
    except Exception as exc:
        log(f"ERRO ao comprar: {type(exc).__name__}: {exc}")
        return 1

    log(f"COMPRA enviada: id={buy_order.get('id')} status={buy_order.get('status')}")

    # 4. Confirma execução.
    try:
        filled_order = call_with_retry(
            exchange.fetch_order, buy_order["id"], SYMBOL
        )
    except Exception as exc:
        log(f"AVISO: não consegui confirmar status da compra: {exc}")
        filled_order = buy_order

    filled_amount = float(filled_order.get("filled") or 0.0)
    log(
        f"COMPRA confirmada: status={filled_order.get('status')} "
        f"filled={filled_amount}"
    )

    if filled_amount <= 0:
        log("ERRO: nada foi executado, abortando venda de fechamento.")
        return 1

    # 5. Vende de volta pra USDT - não deixa posição de teste aberta.
    try:
        sell_amount = float(exchange.amount_to_precision(SYMBOL, filled_amount))
        sell_order = call_with_retry(
            exchange.create_order, SYMBOL, "market", "sell", sell_amount
        )
    except Exception as exc:
        log(
            f"AVISO: compra executada mas venda de fechamento falhou "
            f"({type(exc).__name__}: {exc}) - posição de teste ficou aberta "
            f"na conta testnet, fechar manualmente."
        )
        return 1

    log(f"VENDA de fechamento enviada: id={sell_order.get('id')} status={sell_order.get('status')}")

    balance_after = call_with_retry(exchange.fetch_balance)
    usdt_after = balance_after.get("USDT", {}).get("free", 0.0)
    log(f"Saldo USDT livre após o ciclo: {usdt_after}")

    print("=" * 100)
    print("CICLO DE VALIDAÇÃO CONCLUÍDO (compra + venda no Testnet).")
    print("Nenhuma ordem real foi enviada.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
