from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

import aiosqlite
from aiogram.fsm.context import FSMContext
from forms.user import Form
from datetime import datetime, timedelta

router = Router()

DB_NAME = 'birthday.db'


async def check_daily_birthdays(bot: Bot):
    async with aiosqlite.connect(DB_NAME) as db:
        now = datetime.now()
        today_dm = now.strftime("%d-%m")
        tomorrow_dm = (now + timedelta(days=1)).strftime("%d-%m")
        in_2_days_dm = (now + timedelta(days=2)).strftime("%d-%m")
        
        cursor = await db.execute('SELECT creator_id, name, birthday FROM birthdays')
        users = await cursor.fetchall()
        
        for creator_id, name, birthday_full in users:
            bday_dm = birthday_full[:5] 
            if bday_dm == today_dm:
                text = f"🥳 <b>СЬОГОДНІ!</b> День народження у <b>{name}</b>!\nНе забудь привітати! 🎉"
            elif bday_dm == tomorrow_dm:
                text = f"⏳ <b>НАГАДУВАННЯ:</b> Завтра день народження у <b>{name}</b> ({birthday_full})! 🎁"
            elif bday_dm == in_2_days_dm:
                text = f"⏳ <b>НАГАДУВАННЯ:</b> Через 2 дні день народження у <b>{name}</b> ({birthday_full})! 🎁"
            else:
                continue
                
            try:
                await bot.send_message(creator_id, text, parse_mode="HTML")
            except Exception as e:
                print(f"Помилка надсилання для {creator_id}: {e}")


def get_inline_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='➕ Додати іменинника', callback_data="register_user")],
            [InlineKeyboardButton(text='🗑️ Видалити запис', callback_data="delete_user")],
            [InlineKeyboardButton(text='📋 Список усіх', callback_data="show_users")]
        ]
    )
    return keyboard

@router.message(Command("start"))
async def start(message: Message):
    await save_user(
        tg_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    
    text = "👋 <b>Привіт! Я твій помічник-нагадувач.</b>"
    await message.answer(text, reply_markup=get_inline_keyboard(), parse_mode="HTML")

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS birthdays (
                user_id INTEGER PRIMARY KEY,
                creator_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                birthday TEXT NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                first_seen TEXT
            )
        ''')
        await db.commit()


async def save_user(tg_id: int, username: str, full_name: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR IGNORE INTO users (tg_id, username, full_name, first_seen)
            VALUES (?, ?, ?, ?)
        ''', (tg_id, username, full_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()

async def register_user(creator_id: int, name: str, birthday: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT INTO birthdays (creator_id, name, birthday)
            VALUES (?, ?, ?)
        ''', (creator_id, name, birthday))
        await db.commit()

async def get_users(creator_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT user_id, name, birthday FROM birthdays WHERE creator_id = ?', (creator_id,))
        result = await cursor.fetchall()
        return result

async def delete_user(user_id: int, creator_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            'DELETE FROM birthdays WHERE user_id = ? AND creator_id = ?', (user_id, creator_id)
        )
        await db.commit()
        return cursor.rowcount

@router.callback_query(lambda c: c.data == "register_user")
async def reg(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("👤 Введіть <b>Ім'я та Прізвище</b> іменинника:", parse_mode="HTML")
    await state.set_state(Form.name)
    await callback.answer()

@router.message(Form.name, F.text)
async def process_name(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("⚠️ Потрібно ввести мінімум два слова (Ім'я та Прізвище).\nСпробуйте ще раз:")
        return
    await state.update_data(name=message.text)
    await message.answer("📅 Тепер введіть дату народження у форматі <b>ДД-ММ-РРРР</b>", parse_mode="HTML")
    await state.set_state(Form.birthday)

@router.message(Form.birthday, F.text)
async def process_birthday(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        birthday_dt = datetime.strptime(text, "%d-%m-%Y")
    except ValueError:
        await message.answer("❌ Невірний формат! Використовуйте <b>ДД-ММ-РРРР</b>:", parse_mode="HTML")
        return

    if birthday_dt > datetime.now():
        await message.answer("⏳ Гей, ця людина ще не народилася? Введіть реальну дату:")
        return

    await state.update_data(birthday=text)
    data = await state.get_data()
    
    await register_user(
        creator_id=message.from_user.id,
        name=data["name"],
        birthday=data["birthday"]
    )

    await message.answer(f"🎉 Чудово! <b>{data['name']}</b> додано до списку.", parse_mode="HTML")
    await state.clear()

@router.callback_query(lambda c: c.data == "delete_user")
async def ask_delete(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🗑️ Введіть <b>ID запису</b>, який треба видалити:", parse_mode="HTML")
    await state.set_state(Form.id)
    await callback.answer()

@router.message(Form.id, F.text)
async def process_delete(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ <b>Помилка!</b> ID має бути числом:", parse_mode="HTML")
        return 

    rows_deleted = await delete_user(user_id, message.from_user.id)
    
    if rows_deleted > 0:
        await message.answer(f"✅ Запис під номером <b>ID: {user_id}</b> успішно видалено.", parse_mode="HTML")
        await state.clear()
    else:
        await message.answer("⚠️ <b>Запис не знайдено.</b>", parse_mode="HTML")

@router.callback_query(lambda c: c.data == "show_users")
async def show(callback: CallbackQuery):
    users = await get_users(callback.from_user.id)
    await callback.answer()
    
    if not users:
        await callback.message.answer("📭 Ваш список поки що порожній.")
        return
    
    resp = "📋 <b>Ваш список іменинників:</b>\n\n"
    for user_id, name, birthday in users:
        resp += f"🔹 <b>ID:</b> {user_id} | 👤 {name} | 🎂 {birthday}\n"
    
    await callback.message.answer(resp, parse_mode="HTML")


ADMIN_ID = 741113645  

@router.message(Command("admin_stats"))
async def show_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return 

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT tg_id, username, full_name FROM users')
        users = await cursor.fetchall()
        
    if not users:
        await message.answer("Поки що ніхто не запускав бота.")
        return

    text = "👤 <b>Користувачі бота:</b>\n\n"
    for tg_id, username, name in users:
        user_link = f"@{username}" if username else "немає юзернейму"
        text += f"• {name} ({user_link}) | ID: {tg_id}\n"
    
    await message.answer(text, parse_mode="HTML")




async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT * FROM birthdays')
        result = await cursor.fetchall()
        return result
    

@router.message(Command('show_all'))
async def show_all(message:Message):
    if message.from_user.id != ADMIN_ID:
        return 
    
    users = await get_all_users()

    resp = "📋 <b>Повний список користуівачів:</b>\n\n"
    for user_id, creator_id, name, birthday in users:
        resp += f"🔹 <b>ID:</b> {creator_id} {user_id} | 👤 {name} | 🎂 {birthday}\n"

    await message.answer(resp, parse_mode="HTML")