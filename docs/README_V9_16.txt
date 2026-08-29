V9.16 - SCANNER FORWARD

Executa um ciclo de scanner Binance Spot/USDT e gera:
data/forward_signals.csv

Uso:
python3 src/paper_trading_v9_16.py

Depois:
python3 src/paper_trading_v9_15.py

IMPORTANTE:
- PAPER ONLY;
- não usa CSV legado V8;
- não calcula P&L financeiro;
- não cria ordens reais;
- usa somente candles fechados;
- sinais são apenas entradas para o motor financeiro V9.
