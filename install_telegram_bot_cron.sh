#!/usr/bin/env bash
# Adiciona ao crontab do usuário a linha que mantém o bot do Telegram
# (src/telegram_bot.py) rodando: a cada minuto o cron tenta iniciar, e o
# flock impede segunda cópia - se o bot cair, volta em até 1 minuto.
# Só adiciona se ainda não existir. Mostra o crontab no fim.
set -euo pipefail
REPO=/home/alex/projetos/crypto-radar
LINE="* * * * * cd $REPO && /usr/bin/flock -n /tmp/crypto-radar-telegram-bot.lock $REPO/.venv/bin/python3 src/telegram_bot.py >> $REPO/data/telegram_bot.log 2>&1"

if crontab -l 2>/dev/null | grep -qF "src/telegram_bot.py"; then
    echo "Já está no crontab:"
else
    (crontab -l 2>/dev/null; echo "$LINE") | crontab -
    echo "Adicionado ao crontab:"
fi
crontab -l | grep -F "src/telegram_bot.py"
