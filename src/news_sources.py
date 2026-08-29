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
# Critério de inclusão: só ativos com nome próprio inconfundível.
# Tickers curtos/ambíguos que colidem com palavras comuns do inglês
# (ex: "U", "RE", "HOME", "GPS", "BIO", "TREE", "RED", "SPK") ficam de
# fora de propósito - dariam falso positivo constante num scraper de
# texto livre. Dá pra curar manualmente depois se algum desses vier a
# importar.
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
}
