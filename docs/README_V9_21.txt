CRYPTO RADAR V9.21
====================

Orquestrador forward seguro.

Fluxo:
  scanner_v3.py
      -> scanner_v3_to_v9_20_1.py (preferido, se instalado)
      -> scanner_v3_to_v9.py (fallback)
      -> preflight
      -> V9.18 monitor/close
      -> preflight novamente
      -> V9.17 executor
      -> V9.19 auditoria

Proteções:
- lock com flock para impedir ciclos simultâneos;
- PAPER ONLY;
- V8 legado nunca é usado;
- não cria dados financeiros;
- bloqueia sinais LONG acionáveis duplicados por símbolo+entry_time+timeframe;
- bloqueia mais de 10 sinais acionáveis;
- interrompe o ciclo quando uma etapa crítica falha.

IMPORTANTE:
A V9.21 não altera parâmetros de estratégia. Ela apenas orquestra o
pipeline forward e adiciona barreiras de segurança.

Instalação:
  unzip -o paper_trading_v9_21.zip -d ~/projetos/crypto-radar

Teste:
  cd ~/projetos/crypto-radar
  python3 -m py_compile src/paper_trading_v9_21.py
  python3 src/paper_trading_v9_21.py

Depois, confira:
  cat data/forward_signals.csv
  cat data/paper_trading_v9_open_positions.csv
  cat data/paper_trading_v9_financial_trades.csv
  tail -n 100 data/v9_21_orchestrator.log

CRON:
Não substitua o cron atual imediatamente. Primeiro faça um ciclo manual
e confirme o comportamento. Depois podemos trocar o cron para executar
somente a V9.21.
