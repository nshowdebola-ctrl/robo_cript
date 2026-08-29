CRYPTO RADAR - V8.8 -> V8.12

Ordem:
1. python3 src/paper_trading_v8_8.py
2. python3 src/paper_trading_v8_9.py
3. python3 src/paper_trading_v8_10.py
4. python3 src/paper_trading_v8_11.py
5. python3 src/paper_trading_v8_12.py

Copie os cinco arquivos para src/:
cp paper_trading_v8_8.py paper_trading_v8_9.py paper_trading_v8_10.py paper_trading_v8_11.py paper_trading_v8_12.py ~/projetos/crypto-radar/src/

A cadeia NÃO otimiza parâmetros e NÃO inventa taxas históricas.
V8.8 apenas normaliza o legado; V8.9 mede dependência temporal; V8.10 calcula curvas conservadoras; V8.11 faz estabilidade cronológica descritiva; V8.12 aplica um gate final conservador.
