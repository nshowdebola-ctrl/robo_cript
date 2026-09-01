#!/bin/bash
# Roda a correlação de notícias (Fase 2) UMA VEZ e avisa o resultado
# por WhatsApp - agendado via crontab do sistema pra uma data
# específica (não repete). Se auto-remove do crontab depois de rodar.
#
# Uso: ./run_news_correlation_once.sh

cd "$(dirname "$0")" || exit 1

OUT=$(.venv/bin/python3 src/news_correlation_backtest.py 2>&1)
echo "$(date -Is)" >> data/cron_news_correlation.log
echo "$OUT" >> data/cron_news_correlation.log
echo "----------------------------------------" >> data/cron_news_correlation.log

N_OBS=$(echo "$OUT" | grep -oP 'Observações com retorno calculado: \K[0-9]+')
CORR=$(echo "$OUT" | grep "Correlação (Pearson" | paste -sd ' | ' -)

MSG="Crypto Radar: correlação de notícias rodou de novo após mais dias de coleta. Observações: ${N_OBS:-?}. ${CORR:-sem correlação calculável}. Detalhe completo em data/cron_news_correlation.log."
.venv/bin/python3 src/whatsapp_notify.py "$MSG"

crontab -l | grep -v "run_news_correlation_once.sh" | crontab -
