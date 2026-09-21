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

DB_NAME = '/data/birthday.db'


def next_birthday_date(birthday, today):
    def safe_date(year):
        try:
            return birthday.replace(year=year)
        except ValueError:
            return birthday.replace(year=year, day=28)

    next_birthday = safe_date(today.year)

    if next_birthday < today:
        next_birthday = safe_date(today.year + 1)

    return next_birthday


async def check_daily_birthdays(bot: Bot):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('''
            SELECT birthdays.creator_id,
                   birthdays.name,
                   birthdays.birthday,
                   users.reminder_days
            FROM birthdays
            LEFT JOIN users
                ON birthdays.creator_id = users.tg_id
        ''')
        users = await cursor.fetchall()

    today = datetime.now().date()

    for creator_id, name, birthday_full, reminder_days in users:
        try:
            # Якщо налаштувань немає — залишаємо стару поведінку
            if reminder_days is None:
                selected_days = {0, 1, 2}
            elif reminder_days == "":
                selected_days = set()
            else:
                selected_days = set(map(int, reminder_days.split(",")))

            birthday = datetime.strptime(
                birthday_full,
                "%d-%m-%Y"
            ).date()

            days_left = (
                next_birthday_date(birthday, today) - today
            ).days

            if days_left not in selected_days:
                continue

            if days_left == 0:
                text = (
                    f"🥳 <b>СЬОГОДНІ!</b> День народження "
                    f"у <b>{name}</b>!\n"
                    f"Не забудь привітати! 🎉"
                )

            elif days_left == 1:
                text = (
                    f"⏳ <b>НАГАДУВАННЯ:</b> Завтра день народження "
                    f"у <b>{name}</b> ({birthday_full})! 🎁"
                )

            else:
                word = "дні" if days_left in (2, 3, 4) else "днів"

                text = (
                    f"⏳ <b>НАГАДУВАННЯ:</b> Через {days_left} {word} "
                    f"день народження у <b>{name}</b> "
                    f"({birthday_full})! 🎁"
                )

            await bot.send_message(
                creator_id,
                text,
                parse_mode="HTML"
            )

        except Exception as e:
            print(
                f"Помилка для {creator_id}, "
                f"іменинник {name}: {e}"
            )



def get_inline_keyboard():
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='➕ Додати іменинника', callback_data="register_user")],
            [InlineKeyboardButton(text='🗑️ Видалити запис', callback_data="delete_user")],
            [InlineKeyboardButton(text='📋 Список усіх', callback_data="show_users")],
            [InlineKeyboardButton(text='⚙️ Налаштування нагадувань', callback_data="reminder_settings")]
        ]
    )
    return keyboard


async def get_reminder_days(tg_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT reminder_days FROM users WHERE tg_id = ?",
            (tg_id,)
        )
        result = await cursor.fetchone()

    if not result or result[0] is None:
        return {0, 1, 2}

    if result[0] == "":
        return set()

    return set(map(int, result[0].split(",")))


def get_reminder_keyboard(selected_days):
    options = [
        (0, "У день народження"),
        (1, "За 1 день"),
        (2, "За 2 дні"),
        (3, "За 3 дні"),
        (7, "За 7 днів")
    ]

    buttons = []

    for days, text in options:
        icon = "✅" if days in selected_days else "⬜"

        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {text}",
                callback_data=f"reminder_{days}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(lambda c: c.data == "reminder_settings")
async def reminder_settings(callback: CallbackQuery):
    selected_days = await get_reminder_days(callback.from_user.id)

    await callback.message.answer(
        "🔔 <b>Коли нагадувати про день народження?</b>\n\n"
        "Натисніть на потрібний варіант, щоб увімкнути або вимкнути його:",
        reply_markup=get_reminder_keyboard(selected_days),
        parse_mode="HTML"
    )

    await callback.answer()


@router.callback_query(F.data.regexp(r"^reminder_\d+$"))
async def toggle_reminder(callback: CallbackQuery):
    await save_user(
        tg_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name
    )

    day = int(callback.data.split("_")[1])
    selected_days = await get_reminder_days(callback.from_user.id)

    if day in selected_days:
        selected_days.remove(day)
    else:
        selected_days.add(day)

    reminder_days = ",".join(map(str, sorted(selected_days)))

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET reminder_days = ? WHERE tg_id = ?",
            (reminder_days, callback.from_user.id)
        )
        await db.commit()

    await callback.message.edit_reply_markup(
        reply_markup=get_reminder_keyboard(selected_days)
    )

    await callback.answer("Налаштування збережено ✅")



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
                first_seen TEXT,
                reminder_days TEXT DEFAULT '0,1,2'
            )
        ''')

        # Якщо таблиця users вже існувала — додаємо нове поле
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]

        if "reminder_days" not in column_names:
            await db.execute(
                "ALTER TABLE users ADD COLUMN reminder_days TEXT DEFAULT '0,1,2'"
            )

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
        cursor = await db.execute(
            'SELECT user_id, name, birthday FROM birthdays WHERE creator_id = ?',
            (creator_id,)
        )
        result = await cursor.fetchall()

    today = datetime.now().date()

    def days_until_birthday(user):
        birthday = datetime.strptime(user[2], "%d-%m-%Y").date()

        return (next_birthday_date(birthday, today) - today).days

    return sorted(result, key=days_until_birthday)


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
        await message.answer("⚠️ Потрібно ввести у форматі (Ім'я та Прізвище).\nСпробуйте ще раз:")
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
        await message.answer("Поки що ніхто не запускав бота")
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


@router.message(Command("show_all"))
async def show_all(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Немає доступу")
        return

    users = await get_all_users()

    if not users:
        await message.answer("📭 База порожня")
        return

    chunk = ""
    for user_id, creator_id, name, birthday in users:
        line = f"🔹 ID: {user_id} {creator_id} | 👤 {name} | 🎂 {birthday}\n"

        if len(chunk) + len(line) > 4000:
            await message.answer(chunk, parse_mode="HTML")
            chunk = ""

        chunk += line

    if chunk:
        await message.answer(chunk, parse_mode="HTML")