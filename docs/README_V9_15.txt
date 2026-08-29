CRYPTO RADAR - V9.15

Adapter seguro entre o scanner e o ledger financeiro V9.

Uso:
python3 src/paper_trading_v9_15.py

A V9.15:
- lê data/forward_signals.csv;
- valida symbol, entry_time, entry_price e scenario;
- não usa o CSV V8;
- não inventa fees, notional, quantity ou P&L;
- permanece PAPER ONLY;
- prepara a integração com open_trade()/close_trade().

Se forward_signals.csv estiver ausente ou vazio, nenhum trade é criado.
