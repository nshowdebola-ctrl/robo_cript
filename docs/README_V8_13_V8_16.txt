CRYPTO RADAR — V8.13 → V8.16

Próxima cadeia de auditoria:
V8.13 — exposição e sobreposição temporal
V8.14 — reconstrução de carteira sob hipóteses explícitas
V8.15 — stress test da carteira reconstruída
V8.16 — gate financeiro final

Regra:
- não otimizar parâmetros;
- não alterar silenciosamente o CSV legado;
- separar fatos históricos de hipóteses de reconstrução;
- não tratar P&L legado como capital simultaneamente investido.

A implementação deve usar o CSV legado existente e preservar os resultados V8.8–V8.12.
