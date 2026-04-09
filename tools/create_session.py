"""
Запускай цей скрипт ОДИН РАЗ локально щоб отримати TELEGRAM_SESSION рядок.
Потім вставляєш цей рядок в Railway Variables — і більше ніколи не потрібен телефон.

Запуск:
  pip install telethon python-dotenv
  python tools/create_session.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
PHONE    = os.getenv("TELEGRAM_PHONE", "")

async def main():
    if not API_ID or not API_HASH:
        print("Заповни TELEGRAM_API_ID та TELEGRAM_API_HASH в .env")
        return

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    print("Підключення до Telegram...")
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        await client.start(phone=PHONE or input("Введи номер телефону (+380...): "))
        session_string = client.session.save()
        me = await client.get_me()
        print(f"\nУспішно залогінено як: {me.first_name} (@{me.username})")
        print("\n" + "="*60)
        print("TELEGRAM_SESSION рядок (скопіюй в Railway Variables):")
        print("="*60)
        print(session_string)
        print("="*60)
        print("\nЦей рядок = авторизований сеанс. Зберігай як пароль!")

if __name__ == "__main__":
    asyncio.run(main())
