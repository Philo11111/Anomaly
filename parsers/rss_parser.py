import feedparser
import aiohttp
from datetime import datetime
from loguru import logger
from config import RSS_FEEDS
from analyzers.keyword_filter import check_keywords
from database.db import is_seen

async def fetch_feed(session: aiohttp.ClientSession, url: str) -> list[dict]:
    """Завантажити та розпарсити RSS стрічку."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return []
            content = await resp.text()
            feed = feedparser.parse(content)
            
            articles = []
            for entry in feed.entries[:10]:  # Тільки останні 10
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link = entry.get("link", "")
                published = entry.get("published", "")
                
                articles.append({
                    "title": title,
                    "summary": summary[:500],
                    "link": link,
                    "published": published,
                    "source": feed.feed.get("title", url),
                    "full_text": f"{title} {summary}",
                })
            return articles
    except Exception as e:
        logger.warning(f"RSS fetch error {url}: {e}")
        return []

async def scan_rss_feeds() -> list[dict]:
    """
    Сканує всі RSS джерела.
    Повертає список підозрілих статей з level і keywords.
    """
    alerts = []
    
    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 AnomalityParcer/1.0"}
    ) as session:
        for feed_url in RSS_FEEDS:
            articles = await fetch_feed(session, feed_url)
            
            for article in articles:
                level, keywords = check_keywords(article["full_text"])
                
                if level == "none":
                    continue
                
                # Дедуплікація
                already_seen = await is_seen(article["title"], source="rss")
                if already_seen:
                    continue
                
                article["alert_level"] = level
                article["keywords"] = keywords
                alerts.append(article)
                
                logger.info(
                    f"[RSS:{level.upper()}] {article['title'][:60]}... "
                    f"Keywords: {keywords[:3]}"
                )
    
    return alerts
