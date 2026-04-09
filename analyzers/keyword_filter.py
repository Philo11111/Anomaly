from config import CRITICAL_KEYWORDS, WARNING_KEYWORDS

def check_keywords(text: str) -> tuple[str, list[str]]:
    """
    Перевірка тексту на ключові слова.
    Повертає: (рівень: 'critical'|'warning'|'none', список знайдених слів)
    """
    text_lower = text.lower()
    
    found_critical = [kw for kw in CRITICAL_KEYWORDS if kw in text_lower]
    if found_critical:
        return "critical", found_critical
    
    found_warning = [kw for kw in WARNING_KEYWORDS if kw in text_lower]
    if found_warning:
        return "warning", found_warning
    
    return "none", []

def extract_amount(text: str) -> str | None:
    """Витягти суму з тексту ($1M, $500K, etc.)"""
    import re
    patterns = [
        r'\$[\d,.]+\s*[BMK](?:illion)?',
        r'[\d,.]+\s*(?:million|billion|thousand)\s*(?:USD|USDT|dollars)?',
        r'\$[\d,]+',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None

def extract_protocol(text: str) -> str | None:
    """Спроба витягнути назву протоколу."""
    import re
    # Шукаємо патерни типу "XYZ Protocol", "XYZ Finance", "XYZ DAO"
    match = re.search(
        r'([A-Z][a-zA-Z0-9]+)\s+(?:Protocol|Finance|DAO|DEX|Network|Chain|Bridge)',
        text
    )
    if match:
        return match.group(0)
    return None
