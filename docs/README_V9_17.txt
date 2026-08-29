V9.17 - FORWARD TRADE EXECUTOR

Fluxo:
V9.16 -> forward_signals.csv -> V9.17 -> posições abertas -> fechamento -> ledger financeiro V9.

Características:
- PAPER ONLY;
- não usa retornos/P&L do V8;
- notional, fees e slippage são hipóteses explícitas da V9.17;
- não cria sinais;
- não envia ordens reais;
- abre somente sinais LONG válidos;
- limita posições simultâneas;
- monitora STOP/TARGET/TIME;
- grava somente operações fechadas no ledger financeiro V9.

Comandos:
python3 -m py_compile src/paper_trading_v9_17.py
python3 src/paper_trading_v9_17.py

IMPORTANTE:
As taxas, notional, slippage, stop, target e tempo máximo desta versão são
hipóteses de paper trading. Não são fatos históricos recuperados do V8.
