#!/bin/bash
# Checagem de segurança pro cron "news-correlation-onetime": ele se
# auto-remove do crontab só quando roda com sucesso, então se ainda
# estiver lá nesse horário é sinal de que não disparou (cron do
# sistema fora do ar, erro antes de chegar no self-remove, etc).
# Se auto-remove do crontab depois de checar (também é uso único).
#
# Uso: ./check_news_correlation_ran.sh

cd "$(dirname "$0")" || exit 1

if crontab -l 2>/dev/null | grep -q "news-correlation-onetime"; then
    .venv/bin/python3 src/whatsapp_notify.py \
        "Crypto Radar: ALERTA - a correlação de notícias agendada pra hoje 09h NÃO rodou (a entrada ainda está no crontab). Verificar manualmente."
fi

crontab -l | grep -v "check_news_correlation_ran.sh" | crontab -
