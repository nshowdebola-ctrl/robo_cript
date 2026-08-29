CRYPTO RADAR V9.9 A V9.11
V9.9: open_trade()/close_trade(), sem usar V8 para inventar dados.
V9.10: camada de fechamento financeiro.
V9.11: smoke test isolado, usando arquivo temporário.

Teste:
python3 -m py_compile src/paper_trading_v9_9.py src/paper_trading_v9_10.py src/paper_trading_v9_11.py
python3 src/paper_trading_v9_9.py
python3 src/paper_trading_v9_10.py
python3 src/paper_trading_v9_11.py
