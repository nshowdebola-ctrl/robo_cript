# Crypto Radar — V8.2 → V8.7

Suite de auditoria sem nova otimização.

## Ordem
1. paper_trading_v8_2.py — custos e auditoria financeira
2. paper_trading_v8_3.py — concentração/outliers
3. paper_trading_v8_4.py — estabilidade temporal
4. paper_trading_v8_5.py — stress tests
5. paper_trading_v8_6.py — validação estatística
6. paper_trading_v8_7.py — consolidação final

Todos usam por padrão:
`~/projetos/crypto-radar/data/paper_trading_v8_trades.csv`

Nenhum script altera `scanner_v3.py`, envia ordens ou otimiza parâmetros.

IMPORTANTE:
- O CSV legado não contém fees/notional históricos.
- Cenários de custo são hipotéticos/stress tests.
- A V8.7 não aprova a estratégia se a auditoria continuar limitada pelo CSV legado.
