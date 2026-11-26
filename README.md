# Anomaly

Монітор експлойтів і ринкових аномалій. Він шукає незабезпечені мінти, відтік з мостів і лендінгу, перекази з ключів мінтера або деплоєра, розрив ціни DEX і перпа, новини та нотиси бірж. Подія отримує правиловий бал 0–100 і лишається в стрічці навіть якщо якесь джерело або доставка недоступні.

Алерт ніколи не залежить від LLM. Старий бот мовчки викидав подію, коли модель падала або ставила бал нижче 6. Цього шляху більше немає: бал рахують правила, а жовті й інформаційні події теж зберігаються.

Час на дашборді і в тексті алерту — Europe/Kyiv.

## Запуск однією командою

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m anomaly
```

Дашборд: <http://127.0.0.1:8080/>. Перевірка ендпоінтів: `python -m anomaly probe`. Історичний прогін ACE і SAND: `python -m anomaly backtest`.

Секрети не потрібні. Порожній `.env` (скопіюйте з `.env.example`) нічого не вмикає і нічого не ламає.

## Архітектура

```
джерела M1–M8  →  Event  →  правила 0–100  →  дедуп 2 год  →  JSONL + лог + дашборд
                                                      ↘ webhook і Telegram, лише якщо увімкнені
```

Кожне джерело крутиться у власному циклі. Падіння, 429 або геоблок переводять модуль у `degraded`, вмикають паузу з backoff і не зупиняють процес. HTTP-клієнт має окремий ліміт на кожен хост і список запасних URL. WebSocket перепідключається і змінює ендпоінт.

Стан лежить у `data/anomaly.db` (події і вже побачені новини) і в `data/alerts.jsonl`. Ринкові зрізи тримаються в пам'яті, бо вони оновлюються кожні кілька секунд.

Реєстр (`config/watchlist.yaml` + CoinGecko раз на 6 годин) зв'язує тікер, контракти по мережах, мости, мінтери і те, на яких перп-біржах є ринок.

## Модулі

| Модуль | Що робить | Безкоштовне джерело |
| --- | --- | --- |
| M1 | `Transfer` з нульової адреси і стрибок supply на контрактах зі списку | PublicNode WebSocket: Ethereum, BSC, Base, Arbitrum. Запасний HTTP: офіційні RPC, Pocket, Blast, dRPC |
| M2 | Відтік >30% з адреси мосту/резерву; переказ з мінтера/деплоєра на гаманець з малим nonce | ті самі підписки |
| M3 | Зміна supply SPL mint | `wss://api.mainnet-beta.solana.com`, `accountSubscribe`. Поки в списку немає Solana-мінтів, модуль у `idle` |
| M4 | Нові й зняті ринки Hyperliquid, падіння mark до prev day, деплоєр нового споту | `api.hyperliquid.xyz` info + `wss://api.hyperliquid.xyz/ws` |
| M5 | Розрив ціни DefiLlama і mark перпа >20% | `coins.llama.fi` |
| M6 | Хаки DefiLlama і RSS. Telegram-слухач вимкнений, доки немає сесії | `api.llama.fi/hacks`, RSS |
| M7 | Зупинка депозитів, reduce-only, rollback, security | Upbit, OKX, Bybit, Bitget, Bithumb, прапори Gate, best-effort BingX |
| M8 | OI, funding, mark, обсяг | Hyperliquid, Aster, Lighter, Variational, BingX; довідково Binance, Bybit, OKX, MEXC |

Ліміти в `config/settings.yaml`: Lighter 50 запитів/хв (стеля біржі 60), Variational 8 запитів/10 с (стеля 10), Hyperliquid вага до 1100/хв (стеля 1200), Aster до 2000 ваги/хв. OI Aster, BingX і Binance, де біржа віддає його лише по одному символу, збирається обертанням: спершу тікери зі списку.

## Бал і дедуп

| Сигнал | Бали |
| --- | --- |
| Мінт >5% supply | +50 |
| Відтік мосту/резерву >30% | +40 |
| Мінтер або деплоєр → свіжий гаманець | +30 |
| DEX проти перпа >20% | +25 |
| Корейська біржа зупинила депозит | +30 |
| Довірене джерело | +25 |
| Нотис: security, reduce-only, rollback | +20 |
| Перп на біржі користувача з OI ≥ $500k | +15 |

Червоний: ≥60 вдень і ≥75 вночі (Київ, 00:00–08:00). Жовтий: ≥40, без пуша. Нижче 40 лишається в стрічці як info. Сума ріжеться на 100.

Ключ треда — тікер і вікно 2 години. Нове джерело дописується в той самий тред і бал перераховується з об'єднаних сигналів, а не замінюється слабшою новиною. Пуш (webhook і Telegram) іде лише для червоного, і лише коли тред новий, бал виріс або з'явилося нове джерело. Жовтий пишеться в лог, JSONL і дашборд.

Приклад рядка:

```
🔴 EXPLOIT 80/100 | ACE (Fusionist) | BSC | 19:55 Kyiv
Тип: незабезпечений мінт через bridge-minter
```

## Конфіг

- `config/settings.yaml` — пороги, біржі, URL, ліміти, інтервали, ключові слова.
- `config/watchlist.yaml` — тікери, контракти, мости, мінтери, канали Telegram на майбутнє.
- Змінні середовища перекривають хост, порт, webhook і Telegram. Дивіться `.env.example`.

Щоб додати токен, допишіть блок у `watchlist.yaml` і перезапустіть. Контракт без адреси можна лишити з `coingecko_id`: реєстр підтягне мережі сам.

`DASHBOARD_TOKEN` закриває сторінку і `/api/*`. `/health` лишається відкритим для Railway.

## Дашборд

Ліворуч стан кожного модуля. По центру стрічка з балом і текстом. Вкладка OI / funding показує mark, index, funding і відкритий інтерес по біржі. Пошук фільтрує тікер. Час малюється в Europe/Kyiv у браузері, навіть якщо сервер у UTC.

## Деплой

Linux VPS, systemd:

```bash
sudo useradd --system --home /opt/anomaly anomaly
sudo mkdir -p /opt/anomaly && sudo rsync -a ./ /opt/anomaly/
sudo python3 -m venv /opt/anomaly/.venv
sudo /opt/anomaly/.venv/bin/pip install -r /opt/anomaly/requirements.txt
sudo cp deploy/anomaly.service /etc/systemd/system/anomaly.service
sudo systemctl daemon-reload && sudo systemctl enable --now anomaly
```

Порт 8080 тримайте на localhost або за файрволом. На VPS зручно поставити `DASHBOARD_HOST=127.0.0.1`.

Docker:

```bash
docker compose up --build
```

Railway: репозиторій збирається з `Dockerfile`. Сервіс читає `PORT`, слухає `0.0.0.0` і віддає `/health`. Секрети кладуться в Variables, не в git. Окремий план Railway не обов'язковий для самого процесу: безкоштовні джерела не вимагають ключів.

## Telegram пізніше

Два окремі інтерфейси, обидва вимкнені без секретів.

Бот-доставка (`TelegramBotNotifier`) шле лише червоні алерти:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Слухач каналів (`TelegramSource`) піднімається, лише коли є і API id/hash, і string session:

```bash
python tools/create_session.py
```

Рядок `TELEGRAM_SESSION` кладеться в середовище. Правила слухача вже в коді: один процес, одна сесія, лише `events.NewMessage`, юзернейми резолвляться один раз на старті і кешуються, без циклів `get_entity`, `catch_up=True`. Текст каналу не відправляється в модель. Залежність Telethon навмисно не в базовому `requirements.txt`; для вмикання: `pip install -r requirements-telegram.txt`.

Канали за замовчуванням у `watchlist.yaml`. Старі ручки на кшталт `@peckshieldalert` і `@CertiKCommunity` прибрані: вони мертві або не ті.

## Бектест

`python -m anomaly backtest` читає історичні блоки з безкоштовних RPC і проганяє їх крізь той самий `evaluate_mint_logs`, що й живий вотчер.

- ACE, BSC, блок 135122723, 2026-11-22 17:55:40 UTC (19:55 Київ). Перший мінт у транзакції `0x4dfe4bc1…`. Supply до мінта ~53.73M ACE, один мінт уже >5%. Відправник — мінтер мосту, тому бал червоний.
- SAND, Base, блок 50283189, 2026-08-21 23:42:05 UTC (02:42 Київ). Мінт 50M при supply ~14.6M.
- SAND, BSC, блок 117322026, 2026-08-21 23:42:45 UTC. Мінт 50M при supply ~129.5k.

PublicNode на безкоштовному тарифі не віддає архів (`Archive requests require a personal token`). Для історії бектест іде на `bsc-dataseed`, `bsc.api.pocket.network`, `bsc-mainnet.public.blastapi.io`, `mainnet.base.org` і `base.drpc.org`. Живий вотчер лишається на PublicNode WebSocket: йому потрібен лише свіжий стан. Якщо архів недоступний, `python -m anomaly backtest --fixture` програє збережені логи тих самих транзакцій.

Тести: `pytest`.

## Що свідомо не робить сервіс

Він не торгує. MEXC підключений лише як довідковий тікер. Binance CMS через WebSocket потребує ключ, тому ф'ючерсний premium береться з публічного REST і вимикається, якщо регіон його ріже; спотова ціна лишається на `data-api.binance.vision`. Нотиси Upbit і Bybit з частини мереж закриває Cloudflare або CloudFront: модуль це показує як `degraded` і повторює запит з паузою, а не валить процес.
