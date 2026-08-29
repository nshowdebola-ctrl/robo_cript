CRYPTO RADAR - V9

V9 encerra a interpretação financeira fictícia do CSV legado V8.

Arquivos:
- paper_trading_v9.py
  Motor de simulação financeira com capital, posições, notional, fees e slippage.
  Todos esses custos são hipóteses explícitas da simulação.

- paper_trading_v9_1.py
  Cria o schema financeiro para os próximos trades. Não preenche dados históricos
  inexistentes.

- paper_trading_v9_2.py
  Valida matematicamente os trades financeiros produzidos pela V9.

Fluxo recomendado:
1. python3 src/paper_trading_v9.py
2. python3 src/paper_trading_v9_1.py
3. começar a gerar novos trades com o schema V9.
4. python3 src/paper_trading_v9_2.py --input data/paper_trading_v9_trades.csv

IMPORTANTE:
O CSV V8 legado possui return_pct, mas não possui notional/fees históricos.
Portanto V9 não deve apresentar as taxas hipotéticas como fatos históricos.

V9 continua sendo PAPER TRADING. Não envia ordens reais.
