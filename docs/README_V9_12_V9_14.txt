CRYPTO RADAR V9.12 A V9.14

V9.12
- Adapter para registrar sinais forward no ledger financeiro V9.
- Nunca usa o CSV legado V8 para inventar fees/notional.
- PAPER ONLY.

V9.13
- Gate/contrato do arquivo data/forward_signals.csv.
- Não cria trades sozinho.

V9.14
- Auditoria estrutural e matemática do ledger financeiro V9.
- Não altera dados.

Teste:
python3 -m py_compile src/paper_trading_v9_12.py src/paper_trading_v9_13.py src/paper_trading_v9_14.py
python3 src/paper_trading_v9_13.py
python3 src/paper_trading_v9_14.py

Para integrar sinais fechados:
python3 src/paper_trading_v9_12.py --signals data/forward_signals.csv
