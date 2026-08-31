#!/usr/bin/env python3
"""
CRYPTO RADAR - WATCHDOG DO LOOP DO TESTNET (independente da sessão)

Checa se src/binance_testnet_loop.py está vivo (via PID em
data/binance_testnet_loop.pid) e avisa no WhatsApp (CallMeBot) se
caiu - ao contrário dos monitores da sessão do Claude Code, isso
funciona rodando sozinho pelo cron do sistema, sem precisar do Claude
Code aberto.

Feito pra rodar a cada poucos minutos via cron. Só manda mensagem na
TRANSIÇÃO de estado (vivo -> morto, morto -> vivo de novo) - não fica
repetindo aviso a cada execução enquanto o loop continua caído. Estado
salvo em data/binance_testnet_watchdog_state.json.

Uso:
    python3 src/binance_testnet_watchdog.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from whatsapp_notify import send_whatsapp

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "data" / "binance_testnet_loop.pid"
STATE_FILE = ROOT / "data" / "binance_testnet_watchdog_state.json"


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
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def main() -> int:
    pid = read_pid()
    alive = pid is not None and is_alive(pid)
    state = load_state()
    was_alerted = state.get("alerted", False)

    if alive:
        if was_alerted:
            send_whatsapp("Crypto Radar: loop do testnet voltou a rodar.")
        save_state({"alerted": False})
    else:
        if not was_alerted:
            send_whatsapp(
                "Crypto Radar: ALERTA - loop do testnet caiu ou foi "
                "desativado e não está rodando."
            )
        save_state({"alerted": True})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
