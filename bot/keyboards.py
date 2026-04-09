from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статус", callback_data="status"),
            InlineKeyboardButton(text="📋 Watchlist", callback_data="watchlist"),
        ],
        [
            InlineKeyboardButton(text="🔗 DefiLlama", url="https://defillama.com"),
            InlineKeyboardButton(text="📈 Coinglass", url="https://coinglass.com"),
        ],
        [
            InlineKeyboardButton(text="💹 Velo", url="https://velo.xyz"),
            InlineKeyboardButton(text="⚡ Rekt News", url="https://rekt.news"),
        ],
    ])

def alert_keyboard(link: str = "") -> InlineKeyboardMarkup:
    buttons = []
    if link:
        buttons.append([InlineKeyboardButton(text="🔗 Читати повністю", url=link)])
    buttons.append([
        InlineKeyboardButton(text="✅ Взяв до уваги", callback_data="ack"),
        InlineKeyboardButton(text="❌ Хибна тривога", callback_data="false_alarm"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
