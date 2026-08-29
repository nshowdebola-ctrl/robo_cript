CRYPTO RADAR V9.3 -> V9.5
============================

Objetivo:
Criar o primeiro fluxo financeiro V9 para NOVAS operações, sem reutilizar
o CSV legado V8 como se tivesse fees/notional históricos.

V9.3 - ledger financeiro forward:
  - cria um ledger CSV vazio com schema financeiro explícito;
  - registra operações novas somente quando o usuário/motor fornecer entrada/saída;
  - não inventa taxa, notional ou P&L histórico.

V9.4 - validador:
  - verifica campos obrigatórios;
  - recalcula gross/net/P&L;
  - detecta inconsistências e duplicidades.

V9.5 - relatório:
  - resume o ledger financeiro real da V9;
  - calcula win rate, PF, retorno médio, mediana e drawdown;
  - NÃO compõe trades sobrepostos como se fossem uma única posição.

Uso:
  python3 src/paper_trading_v9_3.py
  python3 src/paper_trading_v9_4.py
  python3 src/paper_trading_v9_5.py

Observação:
O ledger começa vazio. Isso é intencional. O objetivo é que as próximas
operações do paper trading sejam registradas com campos financeiros reais
do próprio motor V9, em vez de tentar recuperar dados ausentes da V8.
