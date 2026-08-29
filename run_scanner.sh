#!/bin/bash

cd /home/alex/projetos/crypto-radar

echo "==================================================" >> data/scanner.log
echo "Scanner V3 iniciado: $(date)" >> data/scanner.log

/home/alex/projetos/crypto-radar/.venv/bin/python \
    src/scanner_v3.py >> data/scanner.log 2>&1

echo "Scanner V3 terminou: $(date)" >> data/scanner.log
