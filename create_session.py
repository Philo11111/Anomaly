from telethon import TelegramClient
from telethon.sessions import StringSession
import asyncio

# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
api_id = 34035425
api_hash = aec3e8de47b50fcb9f8d344a3c5b074c 
# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←

client = TelegramClient('session', api_id, api_hash)

async def main():
    print("Запускаємо QR-вхід...")
    await client.start()                    # це має показати QR-код
    print("✅ Сесія успішно створена!")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())