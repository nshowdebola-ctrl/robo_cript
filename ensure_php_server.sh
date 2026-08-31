#!/bin/bash
# Garante que o PHP dev server do portal (web/) está no ar em
# 127.0.0.1:8000. Feito pra rodar via cron a cada poucos minutos -
# se o processo não estiver rodando (caiu, reboot, etc), sobe de novo.
#
# Uso manual: ./ensure_php_server.sh

cd "$(dirname "$0")" || exit 1

if ! pgrep -f "php -S 127.0.0.1:8000 -t web" > /dev/null; then
    nohup php -S 127.0.0.1:8000 -t web >> data/php_server.log 2>&1 &
    disown
    echo "$(date -Is) PHP server subiu (pid $!)"
fi
