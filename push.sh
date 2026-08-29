#!/bin/bash
# Faz push do branch main pro GitHub usando um token salvo localmente.
#
# Uso:
#   1. Crie o arquivo .git-token na raiz do projeto com o seu Personal
#      Access Token do GitHub (uma linha só, sem espaços):
#        echo "ghp_xxxxxxxxxxxxxxxxxxxx" > .git-token
#      Esse arquivo já está no .gitignore - nunca vai pro repositório.
#   2. Rode: ./push.sh
#
# Se preferir não salvar o token em arquivo, rode sem ele que o script
# pergunta na hora (a digitação fica oculta, não aparece na tela).

set -e

cd "$(dirname "$0")"

TOKEN_FILE=".git-token"
REPO_URL="https://github.com/nshowdebola-ctrl/robo_cript.git"

if [ -f "$TOKEN_FILE" ]; then
    TOKEN=$(cat "$TOKEN_FILE")
else
    read -srp "Token do GitHub (Personal Access Token): " TOKEN
    echo
fi

if [ -z "$TOKEN" ]; then
    echo "Token vazio - abortando."
    exit 1
fi

PUSH_URL="${REPO_URL/https:\/\//https:\/\/$TOKEN@}"

echo "Enviando para $REPO_URL ..."
git push "$PUSH_URL" main

echo "Feito. Verificando..."
git fetch origin main
git log --oneline origin/main..HEAD || true
echo "(vazio acima = tudo sincronizado)"
