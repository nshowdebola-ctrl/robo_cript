#!/bin/bash
# Trunca um arquivo de log (mantém só as últimas N linhas) se ele
# passar de um limite - evita log versionado no git crescer sem
# controle. Histórico antigo é descartado (não arquivado) - esses
# logs são só saída de execução, não dado de trade (isso fica nos
# CSVs/DB, que não são tocados aqui).
#
# Uso: ./rotate_log.sh <arquivo> <limite_linhas> <linhas_a_manter>

set -euo pipefail

FILE="$1"
MAX_LINES="$2"
KEEP_LINES="$3"

[ -f "$FILE" ] || exit 0

LINES=$(wc -l < "$FILE")
if [ "$LINES" -gt "$MAX_LINES" ]; then
    tail -n "$KEEP_LINES" "$FILE" > "$FILE.tmp"
    mv "$FILE.tmp" "$FILE"
    echo "$(date -Is) rotacionado $FILE: $LINES -> $KEEP_LINES linhas"
fi
