#!/bin/bash
# Sobe o loop contínuo do Binance Testnet (src/binance_testnet_loop.py)
# sozinho depois que o computador reinicia - normalmente ele é
# ligado/desligado manualmente pelo portal web (web/testnet.php), mas
# um reboot mata o processo e ele não volta sozinho sem isso.
#
# Feito pra rodar uma vez via cron @reboot. Espera a rede subir antes
# de tentar (a Binance precisa de internet) e só inicia se não tiver
# uma instância já rodando - mesmo padrão de checagem por PID/pgrep
# usado no resto do projeto (ensure_php_server.sh, watchdogs).

cd "$(dirname "$0")" || exit 1

sleep 20

if ! pgrep -f "binance_testnet_loop.py" > /dev/null; then
    nohup .venv/bin/python3 src/binance_testnet_loop.py >> data/binance_testnet_loop_stdout.log 2>&1 &
    disown
    echo "$(date -Is) Loop do testnet subiu depois do boot (pid $!)"
fi
