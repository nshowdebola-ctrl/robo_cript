"""
CRYPTO RADAR - NEWS RADAR V1
Fontes de notícias (feeds RSS públicos, sem API paga) e dicionário de
símbolos para casar manchete -> ativo.

Este módulo é só configuração/dados - não faz rede nem I/O.
"""

from __future__ import annotations

FEEDS: list[dict[str, str]] = [
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"name": "CryptoSlate", "url": "https://cryptoslate.com/feed/"},
    {"name": "BitcoinMagazine", "url": "https://bitcoinmagazine.com/feed"},
    {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/"},
    {"name": "CryptoPotato", "url": "https://cryptopotato.com/feed/"},
    {"name": "TheBlock", "url": "https://www.theblock.co/rss.xml"},
]

# Ticker base (sem "/USDT") -> termos de busca na manchete.
#
# Duas formas de alias:
#   - texto normal (ex: "Bitcoin"): casa como palavra inteira em
#     qualquer lugar da manchete, sem diferenciar maiúsc./minúsc.
#   - "$TICKER" (cashtag): casa só como "$TICKER" literal. Usado para
#     tickers que colidem com palavras comuns do inglês/português (ex:
#     BANK, HOME, GPS, RARE, PEOPLE) - a forma cashtag reduz bastante o
#     falso positivo, ao custo de só pegar manchetes que efetivamente
#     citam o ticker nesse formato (perde alguma cobertura).
#
# Símbolos excluídos por completo (não entram nem como cashtag):
#   - "U" e "EUR": ambíguos demais mesmo com "$" (ex: $U é o ticker real
#     da Unity Software na bolsa; EUR é a moeda Euro, aparece o tempo
#     todo em notícia financeira comum).
SYMBOL_ALIASES: dict[str, list[str]] = {
    "BTC": ["Bitcoin", "BTC"],
    "ETH": ["Ethereum", "Ether", "ETH"],
    "SOL": ["Solana", "SOL"],
    "XRP": ["Ripple", "XRP"],
    "BNB": ["Binance Coin", "BNB"],
    "DOGE": ["Dogecoin", "DOGE"],
    "ADA": ["Cardano", "ADA"],
    "AVAX": ["Avalanche", "AVAX"],
    "LINK": ["Chainlink", "LINK"],
    "DOT": ["Polkadot", "DOT"],
    "LTC": ["Litecoin", "LTC"],
    "BCH": ["Bitcoin Cash", "BCH"],
    "ETC": ["Ethereum Classic", "ETC"],
    "TRX": ["Tron", "TRX"],
    "XLM": ["Stellar", "XLM"],
    "UNI": ["Uniswap", "UNI"],
    "SUI": ["Sui", "SUI"],
    "NEAR": ["NEAR Protocol", "NEAR"],
    "HBAR": ["Hedera", "HBAR"],
    "VET": ["VeChain", "VET"],
    "FIL": ["Filecoin", "FIL"],
    "INJ": ["Injective", "INJ"],
    "PEPE": ["Pepe coin", "PEPE"],
    "SHIB": ["Shiba Inu", "SHIB"],
    "WLD": ["Worldcoin", "WLD"],
    "ONDO": ["Ondo Finance", "ONDO"],
    "ARB": ["Arbitrum", "ARB"],
    "CRV": ["Curve DAO", "Curve Finance", "CRV"],
    "FET": ["Fetch.ai", "FET"],
    "PYTH": ["Pyth Network", "PYTH"],
    "PENDLE": ["Pendle", "PENDLE"],
    "PENGU": ["Pudgy Penguins", "PENGU"],
    "STX": ["Stacks", "STX"],
    "TAO": ["Bittensor", "TAO"],
    "ZEC": ["Zcash", "ZEC"],
    "DASH": ["Dash coin", "DASH"],
    "GALA": ["Gala Games", "GALA"],
    "ENA": ["Ethena", "ENA"],
    "TRUMP": ["Official Trump", "TRUMP coin", "$TRUMP"],
    "XAUT": ["Tether Gold", "XAUT"],
    "USDC": ["USD Coin", "USDC"],
    "USDE": ["Ethena USDe", "USDe"],

    # --- Ampliação: restante dos ~108 símbolos hoje acompanhados pelo
    #     scanner_v3.py. Tickers distintos entram como palavra normal;
    #     tickers que colidem com palavra comum entram só como cashtag.
    "ACE": ["$ACE"],
    "ALLO": ["ALLO"],
    "ALPINE": ["Alpine"],
    "ASTER": ["Aster", "ASTER"],
    "BANK": ["$BANK"],
    "BEAMX": ["BEAMX"],
    "BEL": ["$BEL"],
    "BICO": ["Biconomy", "BICO"],
    "BIO": ["$BIO"],
    "BMT": ["BMT"],
    "BOME": ["Book of Meme", "BOME"],
    "CHIP": ["$CHIP"],
    "CRCLB": ["CRCLB"],
    "DEXE": ["DeXe", "DEXE"],
    "EDEN": ["$EDEN"],
    "ENSO": ["Enso"],
    "ETHFI": ["Ether.fi", "ETHFI"],
    "EURI": ["$EURI"],
    "EWYB": ["EWYB"],
    "FDUSD": ["FDUSD"],
    "GIGGLE": ["$GIGGLE"],
    "GPS": ["$GPS"],
    "GRAM": ["$GRAM"],
    "HEI": ["$HEI"],
    "HEMI": ["$HEMI"],
    "HOME": ["$HOME"],
    "KAITO": ["Kaito"],
    "KORUB": ["KORUB"],
    "MORPHO": ["Morpho"],
    "MOVR": ["Moonriver", "MOVR"],
    "MSTRB": ["MSTRB"],
    "MUB": ["$MUB"],
    "MUBARAK": ["MUBARAK"],
    "NEIRO": ["Neiro"],
    "ONG": ["$ONG"],
    "ONT": ["Ontology", "ONT"],
    "OPN": ["OPN"],
    "PAXG": ["Pax Gold", "PAXG"],
    "PEOPLE": ["$PEOPLE"],
    "PLUME": ["$PLUME"],
    "POL": ["$POL"],
    "PORTAL": ["$PORTAL"],
    "PROM": ["$PROM"],
    "PUMP": ["$PUMP"],
    "RARE": ["$RARE"],
    "RE": ["$RE"],
    "RED": ["$RED"],
    "RLUSD": ["RLUSD"],
    "SKHYB": ["SKHYB"],
    "SNDKB": ["SNDKB"],
    "SNXXB": ["SNXXB"],
    "SOXLB": ["SOXLB"],
    "SPCXB": ["SPCXB"],
    "SPK": ["$SPK"],
    "TREE": ["$TREE"],
    "TUT": ["$TUT"],
    "USD1": ["USD1"],
    "VIRTUAL": ["$VIRTUAL"],
    "WLFI": ["WLFI", "World Liberty Financial"],
    "XPL": ["XPL"],
    "XUSD": ["XUSD"],
    "ZAMA": ["Zama"],
    "ZRO": ["LayerZero", "ZRO"],
}
