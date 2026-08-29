CRYPTO RADAR - PAPER TRADING V9.18

V9.18 monitora as posições abertas pela V9.17 e fecha somente quando:
- STOP de 4%;
- TARGET de 8%;
- tempo máximo de 24 horas.

Usa Binance via CCXT apenas para consultar preços.
Não envia ordens reais.

Custos são hipóteses explícitas da cadeia V9:
- fee saída: 0,10%;
- slippage saída: 0,10%.

O CSV legado V8 não é utilizado para inventar dados.

Fluxo:
V9.16 scanner -> forward_signals.csv
V9.17 abre posições -> paper_trading_v9_open_positions.csv
V9.18 monitora/fecha -> paper_trading_v9_financial_trades.csv
