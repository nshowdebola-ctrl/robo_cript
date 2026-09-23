#!/usr/bin/env python3
"""
CRYPTO RADAR - WATCHDOG DO LOOP LIVE (mainnet, DINHEIRO REAL)

Paralelo de binance_testnet_watchdog.py: checa se
src/binance_live_loop.py está vivo (via PID em
data/binance_live_loop.pid) e avisa no Telegram se caiu. Feito pra
rodar via cron do sistema (não faz parte desta Fase 3 - só entra no
crontab quando a Fase 4 realmente ligar o loop live; até lá, rodar
isto só reporta "não rodando" a cada execução, inofensivo).

Só manda mensagem na TRANSIÇÃO de estado (vivo -> morto, morto ->
vivo). Escrita do state file atômica desde o início (arquivo novo -
diferente do watchdog do testnet, que escreve direto sem tmp+replace;
não repetir essa lacuna aqui).

Uso:
    python3 src/binance_live_watchdog.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from telegram_notify import send_telegram

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "data" / "binance_live_loop.pid"
STATE_FILE = ROOT / "data" / "binance_live_watchdog_state.json"


def is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    raw = PID_FILE.read_text(encoding="utf-8").strip()
    return int(raw) if raw.isdigit() else None


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"alerted": False}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"alerted": False}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def main() -> int:
    pid = read_pid()
    alive = pid is not None and is_alive(pid)
    state = load_state()
    was_alerted = state.get("alerted", False)

    if alive:
        if was_alerted:
            send_telegram("Crypto Radar: [LIVE] loop live voltou a rodar.")
        save_state({"alerted": False})
    else:
        if not was_alerted:
            send_telegram(
                "Crypto Radar: [LIVE] ALERTA - loop live caiu ou foi "
                "desativado e não está rodando."
            )
        save_state({"alerted": True})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
