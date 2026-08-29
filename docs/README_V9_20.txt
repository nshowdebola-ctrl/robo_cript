CRYPTO RADAR - V9.20

Arquivo:
    src/scanner_v3_to_v9.py

Função:
    Adaptar sinais COMPRA/COMPRA FORTE da última rodada gravada pelo
    scanner_v3.py para data/forward_signals.csv.

Não faz:
    - não altera scanner_v3.py
    - não usa o CSV legado V8
    - não inventa dados financeiros
    - não abre posições
    - não envia ordens reais

Fluxo:
    scanner_v3.py
        -> data/crypto_radar.db / scanner_v3_results
        -> scanner_v3_to_v9.py
        -> data/forward_signals.csv
        -> V9.15
        -> V9.17

Teste:
    python3 -m py_compile src/scanner_v3_to_v9.py
    python3 src/scanner_v3_to_v9.py

Depois confira:
    cat data/forward_signals.csv
