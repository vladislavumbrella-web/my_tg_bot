import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from handlers.routes import router, check_daily_birthdays, init_db

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

async def main():
    await init_db()

    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    
    dp.include_router(router)

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    
    scheduler.add_job(
        check_daily_birthdays,
        trigger='cron',
        hour=9,
        minute=0,
        args=[bot] 
    )

    scheduler.start()

    print('Бот успішно запущений через SQLAlchemy.')
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Бот вимкнений')