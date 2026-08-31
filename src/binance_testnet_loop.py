#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE TESTNET LOOP

Roda binance_testnet_trader.py em ciclos contínuos, controlado pelo
portal web (web/testnet.php) via arquivo de PID
(data/binance_testnet_loop.pid) - não é cron do sistema, é um processo
de longa duração que o portal inicia/para sob demanda.

Ainda testnet, ainda sem dinheiro real - a automação aqui é só de
"rodar o ciclo sozinho de tempos em tempos", não de escalar
capital/risco.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

from binance_testnet_executor import ENV_FILE, build_exchange, load_env, log
from binance_testnet_trader import run_cycle

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "data" / "binance_testnet_loop.pid"
LOOP_INTERVAL_SECONDS = 300

_stop = False


def _handle_stop(signum, frame) -> None:
    global _stop
    _stop = True


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    log(f"LOOP iniciado (pid={os.getpid()}, intervalo={LOOP_INTERVAL_SECONDS}s)")

    try:
        env = load_env(ENV_FILE)
        exchange = build_exchange(env)
        exchange.load_markets()
    except Exception as exc:
        log(f"ERRO de configuração, loop encerrado: {exc}")
        PID_FILE.unlink(missing_ok=True)
        return 1

    while not _stop:
        try:
            closed_now, open_count = run_cycle(exchange)
            log(f"LOOP ciclo: {closed_now} fechada(s), {open_count} aberta(s).")
        except Exception as exc:
            log(f"ERRO no ciclo do loop: {type(exc).__name__}: {exc}")

        for _ in range(LOOP_INTERVAL_SECONDS):
            if _stop:
                break
            time.sleep(1)

    log("LOOP encerrado (sinal recebido).")
    PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
