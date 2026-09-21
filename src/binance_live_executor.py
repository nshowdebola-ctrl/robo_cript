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

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from binance_testnet_executor import (  # genérico, reuso direto
    MAX_RETRIES,
    RETRY_BACKOFF_SECONDS,
    call_with_retry,
)

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


class OrderStateUnknown(RuntimeError):
    """Não dá pra saber se a ordem chegou à exchange (erro de rede na
    ordem E na consulta dela). Quem chama NÃO deve reenviar - precisa
    de conferência manual na conta antes. `client_id` permite retomar
    a checagem no ciclo seguinte."""

    def __init__(self, message: str, client_id: str | None = None):
        super().__init__(message)
        self.client_id = client_id


def _find_order_by_client_id(exchange, symbol: str, client_id: str):
    """Ordem registrada na exchange com esse client id, ou None se ela
    não existe. Qualquer outro erro de consulta vira OrderStateUnknown -
    sem saber, reenviar é o que causa ordem em dobro."""
    try:
        return exchange.fetch_order(None, symbol, {"origClientOrderId": client_id})
    except ccxt.OrderNotFound:
        return None
    except Exception as exc:
        raise OrderStateUnknown(
            f"não consegui confirmar se a ordem {client_id} ({symbol}) "
            f"chegou à exchange: {type(exc).__name__}: {exc}",
            client_id=client_id,
        ) from exc


def place_market_order(exchange, symbol: str, side: str, amount: float) -> dict:
    """Ordem a mercado sem risco de duplicar por retry.

    `call_with_retry` reenviava `create_order` em timeout mesmo quando a
    ordem tinha sido executada e só a resposta se perdeu - o que compra
    ou vende em dobro com dinheiro real. Aqui, antes de qualquer novo
    envio, consulta a exchange pelo client id: se a ordem já existe e
    foi executada, devolve ela; se não existe, reenvia com o MESMO id.
    (O client id sozinho não basta: a Binance só recusa id repetido
    enquanto a ordem anterior está aberta, e ordem a mercado preenche
    na hora.)"""
    client_id = "cr" + uuid.uuid4().hex[:30]
    params = {"newClientOrderId": client_id}
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return exchange.create_order(symbol, "market", side, amount, None, params)
        except ccxt.NetworkError as exc:  # inclui timeout, rate limit, DDoS
            last_exc = exc
            wait = RETRY_BACKOFF_SECONDS * attempt
            log(
                f"AVISO: {type(exc).__name__} enviando {side} {symbol} "
                f"(tentativa {attempt}/{MAX_RETRIES}) - confirmando na "
                f"exchange antes de reenviar. Detalhe: {exc}"
            )
            time.sleep(wait)
            found = _find_order_by_client_id(exchange, symbol, client_id)
            if found is None:
                continue  # não chegou: seguro reenviar
            status = found.get("status")
            if status == "closed" and float(found.get("filled") or 0.0) > 0:
                log(
                    f"AVISO: {side} {symbol} já estava executada na "
                    f"exchange (id {found.get('id')}) - não reenviando."
                )
                return found
            if status in ("canceled", "expired", "rejected"):
                continue
            raise OrderStateUnknown(
                f"ordem {client_id} ({symbol}) existe com status "
                f"{status!r} e filled={found.get('filled')} - conferir na conta.",
                client_id=client_id,
            )
    raise RuntimeError(
        f"Falhou após {MAX_RETRIES} tentativas (a ordem não chegou à "
        f"exchange): {last_exc}"
    ) from last_exc


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
