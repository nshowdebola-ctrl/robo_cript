#!/usr/bin/env python3
"""
CRYPTO RADAR - NOTIFICAÇÃO TELEGRAM

Envia mensagem pro Telegram via Bot API oficial - usado pra avisar de
trade fechado e loop caído. Substitui o WhatsApp/CallMeBot (ver
whatsapp_notify.py, mantido no repo mas sem uso nos alertas do live).

Credenciais em .telegram.env (gitignored, raiz do projeto):
    TELEGRAM_BOT_TOKEN=<token que o BotFather devolveu>
    TELEGRAM_CHAT_ID=<chat_id de quem deve receber - só existe depois
    que essa pessoa manda pelo menos uma mensagem pro bot>

Falha de envio (rede fora, token/chat_id inválido, serviço fora do ar)
nunca deve derrubar quem chamou - só retorna False, quem chama decide
o que fazer (normalmente só logar e seguir).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".telegram.env"

TIMEOUT_SECONDS = 10


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def send_telegram(message: str) -> bool:
    """True se a mensagem foi enviada com sucesso. Nunca lança
    exceção."""
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=data, timeout=TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return resp.status == 200 and bool(body.get("ok"))
    except Exception:
        return False


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "Teste do crypto-radar."
    ok = send_telegram(text)
    print("Enviado." if ok else "Falhou.")
    raise SystemExit(0 if ok else 1)
