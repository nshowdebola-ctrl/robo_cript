#!/usr/bin/env python3
"""
CRYPTO RADAR - NOTIFICAÇÃO WHATSAPP (CallMeBot)

Envia mensagem pro WhatsApp via CallMeBot (serviço gratuito de
terceiro, não é a API oficial da Meta/WhatsApp) - usado pra avisar de
trade fechado e loop caído. Ao contrário dos monitores de sessão do
Claude Code, isso funciona mesmo com a sessão fechada, desde que quem
chamar (o loop, ou um watchdog via cron do sistema) esteja rodando.

Credenciais em .callmebot.env (gitignored, raiz do projeto):
    CALLMEBOT_PHONE=<telefone com código do país, sem + nem espaço>
    CALLMEBOT_APIKEY=<key que o CallMeBot devolveu na ativação>

Falha de envio (rede fora, key inválida, serviço fora do ar) nunca
deve derrubar quem chamou - só retorna False, quem chama decide o que
fazer (normalmente só logar e seguir).
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".callmebot.env"

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


def send_whatsapp(message: str) -> bool:
    """True se a mensagem foi enfileirada com sucesso. Nunca lança
    exceção."""
    env = load_env()
    phone = env.get("CALLMEBOT_PHONE", "")
    apikey = env.get("CALLMEBOT_APIKEY", "")
    if not phone or not apikey:
        return False

    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode({
        "phone": phone,
        "text": message,
        "apikey": apikey,
    })
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status == 200 and "queued" in body.lower()
    except Exception:
        return False


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "Teste do crypto-radar."
    ok = send_whatsapp(text)
    print("Enviado." if ok else "Falhou.")
    raise SystemExit(0 if ok else 1)
