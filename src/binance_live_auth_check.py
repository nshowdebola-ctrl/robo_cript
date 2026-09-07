#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE LIVE AUTH CHECK (mainnet, só leitura)

Confirma que a chave real (.binance-live.env) autentica de verdade
contra o Binance Spot MAINNET e mostra o saldo - SEM enviar nenhuma
ordem, comprar ou vender nada. Equivalente ao passo 1 de
binance_testnet_executor.py (a mesma validação que foi feita na
testnet antes de qualquer ordem real de teste), mas isolado num script
próprio que NUNCA chama `create_order` - dá pra auditar isso só lendo
o arquivo: não existe nenhuma chamada de ordem aqui.

Objetivo: validar autenticação, permissões da chave (nota se a API key
tiver permissão de saque habilitada - não deveria, mainnet só precisa
de spot trading) e ver o saldo real, como parte da Fase 2 do roteiro
(criar a chave com o usuário presente) ANTES de rodar
binance_live_trader.py pela primeira vez - que aí sim pode abrir
posição real de verdade se houver sinal acionável.

Uso (manual, sem cron):
    python3 src/binance_live_auth_check.py
"""

from __future__ import annotations

import ccxt

from binance_live_executor import ENV_FILE, build_exchange, call_with_retry, load_env


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - BINANCE LIVE AUTH CHECK (só leitura)")
    print("=" * 100)
    print("AMBIENTE: BINANCE SPOT MAINNET - DINHEIRO REAL")
    print("Este script NUNCA envia ordem - só autentica e lê saldo/permissões.")
    print("-" * 100)

    try:
        env = load_env(ENV_FILE)
        exchange = build_exchange(env)
    except Exception as exc:
        print(f"ERRO de configuração: {exc}")
        return 1

    # 1. Autenticação + saldo.
    try:
        balance = call_with_retry(exchange.fetch_balance)
    except ccxt.AuthenticationError as exc:
        print(f"ERRO de autenticação - chave/secret inválidos ou sem permissão: {exc}")
        return 1
    except Exception as exc:
        print(f"ERRO ao autenticar: {type(exc).__name__}: {exc}")
        return 1

    print("AUTENTICADO com sucesso na conta mainnet real.")

    usdt = balance.get("USDT", {})
    print(f"Saldo USDT: livre={usdt.get('free', 0.0)} | travado={usdt.get('used', 0.0)} | total={usdt.get('total', 0.0)}")

    non_zero = {
        asset: info.get("total", 0.0)
        for asset, info in balance.get("total", {}).items() if isinstance(info, (int, float)) and info > 0
    } if isinstance(balance.get("total"), dict) else {}
    if non_zero:
        print(f"Outros ativos com saldo > 0 ({len(non_zero)}): {', '.join(sorted(non_zero)[:15])}"
              + (" ..." if len(non_zero) > 15 else ""))
    else:
        print("Nenhum outro ativo com saldo > 0 além do USDT (ou saldo zerado).")

    # 2. Permissões da chave - aviso se saque estiver habilitado (não deveria).
    try:
        api_status = call_with_retry(exchange.sapi_get_account_apirestrictions)
        can_withdraw = api_status.get("enableWithdrawals")
        can_trade = api_status.get("enableSpotAndMarginTrading")
        print(f"Permissões da chave: trading_spot={can_trade} | saque_habilitado={can_withdraw}")
        if can_withdraw:
            print(
                "AVISO IMPORTANTE: esta chave tem permissão de SAQUE habilitada - "
                "recomendação é criar uma chave só com trading spot, sem saque, "
                "e trocar por essa. Não é um erro deste script, é uma configuração "
                "que se ajusta no site da Binance."
            )
    except Exception as exc:
        print(f"AVISO: não consegui checar permissões da chave via API ({type(exc).__name__}: {exc}) - "
              "confirme manualmente no site da Binance que é só-spot, sem saque.")

    # 3. Confirma que os mercados carregam (usado pelo trader/loop de verdade).
    try:
        markets = call_with_retry(exchange.load_markets)
        print(f"Mercados carregados: {len(markets)} pares disponíveis no mainnet.")
    except Exception as exc:
        print(f"AVISO: falha ao carregar mercados: {type(exc).__name__}: {exc}")

    print("=" * 100)
    print("Checagem concluída. NENHUMA ordem foi enviada, NENHUM saldo foi movimentado.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
