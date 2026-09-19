#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE LIVE LOOP (mainnet, DINHEIRO REAL)

Paralelo de binance_testnet_loop.py: roda binance_live_trader.py em
ciclos contínuos, controlado pelo portal (web/live.php) via arquivo de
PID (data/binance_live_loop.pid).

Mesmo mecanismo de segurança do trader: tenta `load_env(ENV_FILE)`
antes de qualquer chamada ccxt. Sem `.binance-live.env`, encerra com
erro limpo sem jamais construir o exchange - segundo ponto
independente (além de binance_live_trader.main()) que garante "sem
chave, sem ordem real" nesta fase, já que é este arquivo que o portal
inicia diretamente.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from binance_live_executor import ENV_FILE, build_exchange, load_env, log
from binance_live_trader import run_cycle

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "data" / "binance_live_loop.pid"
LOOP_INTERVAL_SECONDS = 60

_stop = False


def _handle_stop(signum, frame) -> None:
    global _stop
    _stop = True


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    log(f"[LIVE] LOOP iniciado (pid={os.getpid()}, intervalo={LOOP_INTERVAL_SECONDS}s)")

    try:
        env = load_env(ENV_FILE)
        exchange = build_exchange(env)
        exchange.load_markets()
    except Exception as exc:
        log(f"[LIVE] ERRO de configuração, loop encerrado: {exc}")
        PID_FILE.unlink(missing_ok=True)
        return 1

    while not _stop:
        try:
            closed_now, open_count, halted = run_cycle(exchange)
            log(
                f"[LIVE] LOOP ciclo: {closed_now} fechada(s), {open_count} aberta(s)."
                + (" CIRCUIT BREAKER ATIVO." if halted else "")
            )
        except Exception as exc:
            log(f"[LIVE] ERRO no ciclo do loop: {type(exc).__name__}: {exc}")

        for _ in range(LOOP_INTERVAL_SECONDS):
            if _stop:
                break
            time.sleep(1)

    log("[LIVE] LOOP encerrado (sinal recebido).")
    PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
