# AnomalityParcer

Telegram-бот для моніторингу крипто-аномалій: DeFi хаки, exploit, whale рухи, падіння TVL, цінові аномалії.

## Як запустити

### Крок 1 — Підготовка файлів

```bash
git clone <repo>
cd anomalityparcer
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заповни `.env`:
- `BOT_TOKEN` — від @BotFather
- `ADMIN_CHAT_ID` — від @userinfobot
- `ANTHROPIC_API_KEY` або `OPENROUTER_API_KEY`
- `TELEGRAM_API_ID` і `TELEGRAM_API_HASH` — з https://my.telegram.org/apps

### Крок 2 — Отримати Telethon session (один раз)

```bash
python tools/create_session.py
```

Введи номер телефону → отримаєш SMS → введи код.
Скрипт видасть довгий рядок — це твій `TELEGRAM_SESSION`.
Скопіюй його. Телефон після цього більше не потрібен.

### Крок 3 — Деплой на Railway

1. Завантаж проєкт на GitHub (`.env` не потрапить туди завдяки `.gitignore`)
2. На Railway: New Project → Deploy from GitHub repo
3. Settings → Variables — додай всі змінні з `.env.example`:
   - Всі ключі вводяться вручну прямо там
   - `TELEGRAM_SESSION` — вставляєш довгий рядок з кроку 2
4. Deploy → бот запустився, телефон вимкнений — все працює

### Структура

```
anomalityparcer/
├── main.py                    # Точка входу
├── config.py                  # Конфігурація
├── scheduler.py               # Планувальник задач
├── requirements.txt
├── .env.example               # Шаблон змінних (без секретів)
├── .gitignore                 # .env і .session ніколи не в git
├── tools/
│   └── create_session.py      # Генератор Telethon session (запускати 1 раз локально)
├── bot/
│   ├── handlers.py            # /start /status /watchlist
│   └── keyboards.py
├── parsers/
│   ├── rss_parser.py          # RSS новини
│   ├── telegram_parser.py     # Telethon — читання каналів
│   ├── price_monitor.py       # Binance WebSocket
│   └── onchain_monitor.py     # Відстеження гаманців хакерів
├── analyzers/
│   ├── keyword_filter.py      # Фільтр ключових слів
│   ├── defillama.py           # TVL моніторинг
│   └── ai_analyzer.py         # AI аналіз (Anthropic або OpenRouter)
├── database/
│   └── db.py                  # SQLite — дедуплікація
└── utils/
    └── formatter.py           # Форматування Telegram повідомлень
```

## Як працює Telethon

Telethon — Python бібліотека для Telegram User API (не Bot API).
Логіниться як звичайний юзер і читає публічні канали.

**Телефон потрібен ОДИН РАЗ** — при запуску `create_session.py`.
Після цього сесія зберігається як рядок (`TELEGRAM_SESSION`).
На Railway цей рядок живе у Variables — телефон назавжди вимкнений.

Сесія діє роками поки ти сам не виходиш з акаунту в Telegram.

## Витрати на місяць

| Сервіс | Вартість |
|--------|----------|
| Railway Hobby plan | $5/міс |
| OpenRouter + Gemini Flash | Безкоштовно |
| Etherscan API | Безкоштовно |
| DefiLlama API | Безкоштовно |
| RSS + Binance WS | Безкоштовно |
| **Разом** | **~$5/міс** |

Anthropic Haiku як альтернатива: +$1-3/міс при активному використанні.
