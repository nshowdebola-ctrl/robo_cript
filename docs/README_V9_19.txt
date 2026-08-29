V9.19 — Auditoria do ciclo forward

A V9.19 somente lê:
- paper_trading_v9_open_positions.csv
- paper_trading_v9_financial_trades.csv

Ela verifica schema, campos numéricos, timestamps e duplicidades.
Não cria trades.
Não fecha posições.
Não altera arquivos.
Não usa o CSV legado V8.

Fluxo atual:
V9.16 scanner
 -> V9.15 valida sinais
 -> V9.17 abre posições
 -> V9.18 monitora e fecha
 -> ledger financeiro V9
 -> V9.19 audita integridade
