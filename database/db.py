import aiosqlite
import hashlib
from datetime import datetime, timedelta
from loguru import logger

DB_PATH = "anomalityparcer.db"

async def init_db():
    """Ініціалізація БД при старті."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE NOT NULL,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tvl_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                protocol TEXT NOT NULL,
                tvl REAL NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                price REAL NOT NULL,
                volume_24h REAL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_seen_hash ON seen_alerts(hash)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_tvl_protocol ON tvl_snapshots(protocol, recorded_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_snapshots(symbol, recorded_at)")
        await db.commit()
    logger.info("Database initialized")

def make_hash(text: str) -> str:
    """Хеш для дедуплікації."""
    return hashlib.md5(text.encode()).hexdigest()

async def is_seen(text: str, source: str = "") -> bool:
    """Перевірка чи вже бачили це повідомлення."""
    h = make_hash(text)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM seen_alerts WHERE hash = ?", (h,)
        )
        row = await cursor.fetchone()
        if row:
            return True
        # Зберігаємо
        await db.execute(
            "INSERT OR IGNORE INTO seen_alerts (hash, source) VALUES (?, ?)",
            (h, source)
        )
        await db.commit()
        return False

async def cleanup_old_alerts(days: int = 7):
    """Видалення старих записів."""
    cutoff = datetime.now() - timedelta(days=days)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM seen_alerts WHERE created_at < ?", (cutoff,)
        )
        await db.commit()

async def save_tvl(protocol: str, tvl: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO tvl_snapshots (protocol, tvl) VALUES (?, ?)",
            (protocol, tvl)
        )
        await db.commit()

async def get_tvl_hour_ago(protocol: str) -> float | None:
    """TVL протоколу годину тому."""
    hour_ago = datetime.now() - timedelta(hours=1)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """SELECT tvl FROM tvl_snapshots
               WHERE protocol = ? AND recorded_at <= ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (protocol, hour_ago)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

async def save_price(symbol: str, price: float, volume: float = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO price_snapshots (symbol, price, volume_24h) VALUES (?, ?, ?)",
            (symbol, price, volume)
        )
        await db.commit()

async def get_price_minutes_ago(symbol: str, minutes: int = 5) -> float | None:
    """Ціна N хвилин тому."""
    cutoff = datetime.now() - timedelta(minutes=minutes)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """SELECT price FROM price_snapshots
               WHERE symbol = ? AND recorded_at <= ?
               ORDER BY recorded_at DESC LIMIT 1""",
            (symbol, cutoff)
        )
        row = await cursor.fetchone()
        return row[0] if row else None
