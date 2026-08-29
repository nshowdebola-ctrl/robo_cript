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

# Cada forma (singular/plural/tempo verbal) é listada explicitamente
# em vez de casar por radical - radical curto demais (ex: "ban", "drop")
# bateria em palavras não relacionadas ("banana", "Dropbox").
POSITIVE_TERMS = [
    "surge", "surges", "surged", "soar", "soars", "soared",
    "rally", "rallies", "rallied", "bullish",
    "breakout", "all-time high", "record high", "outperform",
    "adoption", "partnership",
    "integrates", "integration", "integrated", "launches", "launched",
    "upgrade", "upgrades", "upgraded",
    "approval", "approved", "approves", "etf approved",
    "institutional inflow", "inflow", "buy the dip",
    "recovery", "recovers", "recovered",
    "rebound", "rebounds", "rebounded", "rebounding", "green",
    "climb", "climbs", "climbed", "climbing",
    "jump", "jumps", "jumped", "jumping",
    "gain", "gains", "gained", "gaining",
    "advance", "advances", "advanced",
    "rise", "rises", "rose", "risen", "rising",
    "spike", "spikes", "spiked",
    "rocket", "rockets", "rocketed", "moons", "mooning",
    "extends gains", "beats expectations",
    "alta", "dispara", "disparou", "recorde", "aprovação", "aprovado",
    "parceria", "recuperação", "valorização", "sobe", "subiu", "avança",
]

NEGATIVE_TERMS = [
    "crash", "crashes", "crashed",
    "plunge", "plunges", "plunged", "bearish",
    "selloff", "sell-off", "dump", "dumps", "dumped",
    "collapse", "collapses", "collapsed",
    "hack", "hacked", "exploit", "exploited",
    "lawsuit", "sues", "sued", "suing",
    "ban", "bans", "banned", "banning", "crackdown",
    "investigation", "investigated", "investigating",
    "fraud", "scam", "bankruptcy", "bankrupt",
    "delist", "delisted", "outflow",
    "liquidation", "liquidated", "sec sues",
    "fall", "falls", "fell", "fallen", "falling",
    "drop", "drops", "dropped", "dropping",
    "sink", "sinks", "sank", "sunk", "sinking",
    "tumble", "tumbles", "tumbled",
    "slide", "slides", "slid", "sliding",
    "slump", "slumps", "slumped",
    "decline", "declines", "declined",
    "retreat", "retreats", "retreated",
    "weaken", "weakens", "weakened",
    "rejection", "rejected",
    "queda", "despenca", "despencou", "processo", "proibição",
    "proibido", "hackeada", "hackeado", "fraude", "falência",
    "investigação", "cai", "caiu", "recua", "tomba", "afunda",
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
