import os
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, select, delete, insert

from forms.user import Form

router = Router()

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

class Birthday(Base):
    __tablename__ = "birthdays"
    user_id = Column(Integer, primary_key=True)
    creator_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    birthday = Column(String, nullable=False)

class User(Base):
    __tablename__ = "users"
    tg_id = Column(Integer, primary_key=True)
    username = Column(String)
    full_name = Column(String)
    first_seen = Column(String)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def save_user(tg_id: int, username: str, full_name: str):
    async with async_session() as session:
        async with session.begin():
            user = await session.get(User, tg_id)
            if not user:
                session.add(User(
                    tg_id=tg_id, 
                    username=username, 
                    full_name=full_name, 
                    first_seen=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))

async def register_birthday(creator_id: int, name: str, birthday: str):
    async with async_session() as session:
        async with session.begin():
            session.add(Birthday(creator_id=creator_id, name=name, birthday=birthday))

async def get_users_birthdays(creator_id: int):
    async with async_session() as session:
        result = await session.execute(select(Birthday).where(Birthday.creator_id == creator_id))
        return result.scalars().all()

async def delete_birthday_record(user_id: int, creator_id: int):
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                delete(Birthday).where(Birthday.user_id == user_id, Birthday.creator_id == creator_id)
            )
            return result.rowcount


async def check_daily_birthdays(bot: Bot):
    async with async_session() as session:
        now = datetime.now()
        today_dm = now.strftime("%d-%m")
        tomorrow_dm = (now + timedelta(days=1)).strftime("%d-%m")
        in_2_days_dm = (now + timedelta(days=2)).strftime("%d-%m")
        
        result = await session.execute(select(Birthday))
        users = result.scalars().all()
        
        for user in users:
            bday_dm = user.birthday[:5]
            text = None
            if bday_dm == today_dm:
                text = f"🥳 <b>СЬОГОДНІ!</b> День народження у <b>{user.name}</b>!\nНе забудь привітати! 🎉"
            elif bday_dm == tomorrow_dm:
                text = f"⏳ <b>НАГАДУВАННЯ:</b> Завтра день народження у <b>{user.name}</b> ({user.birthday})! 🎁"
            elif bday_dm == in_2_days_dm:
                text = f"⏳ <b>НАГАДУВАННЯ:</b> Через 2 дні день народження у <b>{user.name}</b> ({user.birthday})! 🎁"
            
            if text:
                try:
                    await bot.send_message(user.creator_id, text, parse_mode="HTML")
                except Exception as e:
                    print(f"Помилка надсилання: {e}")


def get_inline_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='➕ Додати іменинника', callback_data="register_user")],
        [InlineKeyboardButton(text='🗑️ Видалити запис', callback_data="delete_user")],
        [InlineKeyboardButton(text='📋 Список усіх', callback_data="show_users")]
    ])

@router.message(Command("start"))
async def start(message: Message):
    await save_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await message.answer("👋 <b>Привіт! Я твій помічник-нагадувач.</b>", 
                         reply_markup=get_inline_keyboard(), parse_mode="HTML")

@router.callback_query(lambda c: c.data == "register_user")
async def reg(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("👤 Введіть <b>Ім'я та Прізвище</b> іменинника:")
    await state.set_state(Form.name)
    await callback.answer()

@router.message(Form.name, F.text)
async def process_name(message: Message, state: FSMContext):
    if len(message.text.strip().split()) < 2:
        await message.answer("⚠️ Потрібно мінімум два слова. Спробуйте ще раз:")
        return
    await state.update_data(name=message.text)
    await message.answer("📅 Введіть дату у форматі <b>ДД-ММ-РРРР</b>")
    await state.set_state(Form.birthday)

@router.message(Form.birthday, F.text)
async def process_birthday(message: Message, state: FSMContext):
    try:
        datetime.strptime(message.text.strip(), "%d-%m-%Y")
    except ValueError:
        await message.answer("❌ Невірний формат! Треба ДД-ММ-РРРР:")
        return

    data = await state.get_data()
    await register_birthday(message.from_user.id, data["name"], message.text.strip())
    await message.answer(f"🎉 <b>{data['name']}</b> додано до списку.")
    await state.clear()

@router.callback_query(lambda c: c.data == "show_users")
async def show(callback: CallbackQuery):
    users = await get_users_birthdays(callback.from_user.id)
    if not users:
        await callback.message.answer("📭 Список порожній.")
        return
    resp = "📋 <b>Ваш список:</b>\n\n"
    for u in users:
        resp += f"🔹 <b>ID:</b> {u.user_id} | 👤 {u.name} | 🎂 {u.birthday}\n"
    await callback.message.answer(resp)
    await callback.answer()

@router.callback_query(lambda c: c.data == "delete_user")
async def ask_delete(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🗑️ Введіть <b>ID запису</b> для видалення:")
    await state.set_state(Form.id)
    await callback.answer()

@router.message(Form.id, F.text)
async def process_delete(message: Message, state: FSMContext):
    try:
        rows = await delete_birthday_record(int(message.text), message.from_user.id)
        if rows > 0:
            await message.answer(f"✅ Запис {message.text} видалено.")
            await state.clear()
        else:
            await message.answer("⚠️ Запис не знайдено.")
    except ValueError:
        await message.answer("❌ ID має бути числом.")

