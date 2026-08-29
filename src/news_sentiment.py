"""
CRYPTO RADAR - NEWS RADAR V1
Scorer de sentimento léxico (sem modelo pesado / sem dependência nova).

Abordagem simples e transparente de propósito: conta termos
bullish/bearish/regulatórios na manchete (PT + EN) e retorna um score
-1..+1. Se essa aproximação se mostrar fraca depois de validar contra
dado real (ver src/news_correlation_backtest.py, fase 2), é o ponto
certo pra trocar por um modelo tipo FinBERT/CryptoBERT - mesma lógica
de evolução que o projeto já seguiu de technical.py -> technical_v2.py.
"""

from __future__ import annotations

import re

POSITIVE_TERMS = [
    "surge", "surges", "soar", "soars", "rally", "rallies", "bullish",
    "breakout", "all-time high", "record high", "outperform",
    "adoption", "partnership", "integrates", "integration", "launches",
    "upgrade", "approval", "approved", "etf approved", "institutional inflow",
    "inflow", "buy the dip", "recovery", "rebound", "green",
    "alta", "dispara", "disparou", "recorde", "aprovação", "aprovado",
    "parceria", "recuperação", "valorização",
]

NEGATIVE_TERMS = [
    "crash", "crashes", "plunge", "plunges", "bearish", "selloff",
    "sell-off", "dump", "dumps", "collapse", "hack", "hacked", "exploit",
    "exploited", "lawsuit", "sues", "sued", "ban", "banned", "crackdown",
    "investigation", "fraud", "scam", "bankruptcy", "bankrupt", "delist",
    "delisted", "outflow", "liquidation", "liquidated", "sec sues",
    "queda", "despenca", "despencou", "processo", "proibição", "proibido",
    "hackeada", "hackeado", "fraude", "falência", "investigação",
]


def _count_terms(text_lower: str, terms: list[str]) -> int:
    count = 0
    for term in terms:
        pattern = r"\b" + re.escape(term) + r"\b"
        count += len(re.findall(pattern, text_lower))
    return count


def score_text(text: str) -> tuple[float, str]:
    """
    Retorna (score, label). score em [-1, 1].
    label em {"POSITIVO", "NEUTRO", "NEGATIVO"}.
    """

    text_lower = text.lower()

    pos = _count_terms(text_lower, POSITIVE_TERMS)
    neg = _count_terms(text_lower, NEGATIVE_TERMS)

    total = pos + neg
    if total == 0:
        return 0.0, "NEUTRO"

    score = (pos - neg) / total

    if score > 0.2:
        label = "POSITIVO"
    elif score < -0.2:
        label = "NEGATIVO"
    else:
        label = "NEUTRO"

    return round(score, 4), label
