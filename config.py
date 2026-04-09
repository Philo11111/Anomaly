import os
from dotenv import load_dotenv

load_dotenv()

# === TELEGRAM BOT ===
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))

# === AI ===
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
USE_OPENROUTER     = bool(OPENROUTER_API_KEY and not ANTHROPIC_API_KEY)
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")

# === TELETHON (string session — не потрібен телефон на сервері) ===
TELEGRAM_API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION  = os.getenv("TELEGRAM_SESSION", "")   # генерується через tools/create_session.py
TELEGRAM_PHONE    = os.getenv("TELEGRAM_PHONE", "")     # тільки для create_session.py

# === THRESHOLDS ===
PRICE_CHANGE_THRESHOLD = float(os.getenv("PRICE_CHANGE_THRESHOLD", "4.0"))
TVL_DROP_THRESHOLD     = float(os.getenv("TVL_DROP_THRESHOLD", "8.0"))
MIN_AI_SCORE           = int(os.getenv("MIN_AI_SCORE", "6"))
WHALE_TX_USD           = float(os.getenv("WHALE_TX_USD", "1000000"))

# === INTERVALS (seconds) ===
RSS_CHECK_INTERVAL    = int(os.getenv("RSS_CHECK_INTERVAL", "90"))
TVL_CHECK_INTERVAL    = int(os.getenv("TVL_CHECK_INTERVAL", "180"))
ONCHAIN_CHECK_INTERVAL = int(os.getenv("ONCHAIN_CHECK_INTERVAL", "60"))

# === ON-CHAIN APIs ===
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
SOLSCAN_API_KEY   = os.getenv("SOLSCAN_API_KEY", "")

# === RSS SOURCES ===
RSS_FEEDS = [
    "https://rekt.news/feed/",
    "https://cointelegraph.com/rss",
    "https://decrypt.co/feed",
    "https://theblock.co/rss.xml",
    "https://cryptoslate.com/feed/",
    "https://blockworks.co/feed",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://protos.com/feed/",
    "https://www.thedefiant.io/feed",
]

# === TELEGRAM CHANNELS ===
TELEGRAM_CHANNELS = [
    "@peckshieldalert",
    "@lookonchain",
    "@zachxbt",
    "@ArkhamIntelligence",
    "@CertiKCommunity",
    "@SlowMist_Team",
    "@DeFiHackLabs",
    "@blocksecteam",
    "@hackenclub",
    "@web3isgreat",
    "@solanafloor",
    "@wublockchain",
]

# === CRITICAL KEYWORDS ===
CRITICAL_KEYWORDS = [
    "hack","hacked","exploit","exploited","drained","drain","stolen","theft",
    "compromised","vulnerability","attack","attacked","rug pull","rugpull","rug",
    "emergency pause","paused","suspended","funds at risk","funds stolen",
    "security breach","breach","unauthorized","flash loan","oracle manipulation",
    "oracle attack","private key","admin key","multisig","durable nonce",
    "price manipulation","wash trading","front-run","sandwich attack",
    "$500k","$1m","$2m","$5m","$10m","$20m","$50m","$100m",
    "500,000","million stolen","million drained",
    "bridge hack","bridge exploit","bridge attack","tornado cash",
    "unusual activity","unusual outflow","suspicious transaction",
    "suspicious wallet","active attack","ongoing attack",
]

# === WARNING KEYWORDS ===
WARNING_KEYWORDS = [
    "investigation","incident","warning","caution","alert","anomaly",
    "delisted","halt","halted","emergency","critical","urgent",
    "abnormal","irregular","unusual","pausing","freezing","freeze",
    "large withdrawal","large transfer","insolvency","insolvent",
]

# === ASSETS (Binance WebSocket) ===
TRACKED_ASSETS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","AVAXUSDT","ADAUSDT",
    "DOTUSDT","NEARUSDT","SUIUSDT","APTUSDT","TONUSDT",
    "ARBUSDT","OPUSDT","MATICUSDT","STRKUSDT",
    "UNIUSDT","AAVEUSDT","CRVUSDT","MKRUSDT","COMPUSDT","GMXUSDT","DYDXUSDT",
    "JUPUSDT","RAYUSDT","JITOUSDT","PYTHUSDT","DRIFTUSDT","WIFUSDT","BONKUSDT",
    "OKBUSDT","HTUSDT","KCSUSDT",
    "DOGEUSDT","SHIBUSDT","PEPEUSDT",
    "EIGENUSDT","TAOUSDT","WLDUSDT",
]

# === DEFI PROTOCOLS (DefiLlama TVL) ===
TRACKED_PROTOCOLS = [
    "drift-protocol","jupiter","marinade","jito","raydium","orca",
    "meteora","solend","marginfi","kamino",
    "aave","aave-v3","compound","uniswap","curve-dex","balancer",
    "lido","makerdao","spark","pendle","eigenlayer","ethena",
    "wormhole","stargate","across-protocol","hop-protocol",
    "arbitrum","optimism","base",
]

# === TRACKED WALLETS ===
TRACKED_WALLETS_ETH = [
    "0xAa843eD65C1f061F111B5289169731351c5e57C1",  # Drift attacker ETH
]
TRACKED_WALLETS_SOL = [
    "HkGz4KmoZ7Zmk7HN6ndJ31UJ1qZ2qgwQxgVqQwovpZES",  # Drift attacker SOL
]
