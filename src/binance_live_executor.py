#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE LIVE EXECUTOR (mainnet, dinheiro real)

Auth + construção do exchange pro Binance Spot MAINNET, isolado de
propósito de binance_testnet_executor.py - nunca deixa
`set_sandbox_mode(True)` vazar pro lado real por engano (aqui é sempre
explicitamente `False`).

FASE 3 do roteiro de dinheiro real (ver memória do projeto): esta é a
engenharia que PODE ser adiantada sem chave real. Nenhuma ordem real é
enviada por nada deste repositório até `.binance-live.env` existir -
esse arquivo nunca é criado automaticamente, só manualmente pelo
usuário, presente, na Fase 2 do roteiro.

Credenciais em .binance-live.env (gitignored, raiz do projeto),
NOMES DIFERENTES dos de testnet de propósito (um erro de copiar/colar
o arquivo/variável errada falha alto em vez de silenciosamente
"funcionar" contra o ambiente errado):
    BINANCE_LIVE_API_KEY=...
    BINANCE_LIVE_API_SECRET=...
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import ccxt

from binance_testnet_executor import call_with_retry  # genérico, reuso direto

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".binance-live.env"
LOG_FILE = ROOT / "data" / "binance_live.log"


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
            f"{path} não encontrado - nenhuma chave real configurada "
            "ainda. Engenharia pronta, trading real desabilitado até "
            "este arquivo existir (crie com BINANCE_LIVE_API_KEY e "
            "BINANCE_LIVE_API_SECRET quando decidir ativar de verdade, "
            "com o usuário presente)."
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
    api_key = env.get("BINANCE_LIVE_API_KEY", "")
    api_secret = env.get("BINANCE_LIVE_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError(
            f"BINANCE_LIVE_API_KEY/BINANCE_LIVE_API_SECRET ausentes em {ENV_FILE}."
        )

    exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    # ORDENS REAIS - nunca mude isto para True.
    exchange.set_sandbox_mode(False)
    return exchange
