import re
import sqlite3
from aiogram import F, Router
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.filters.state import State, StatesGroup
from aiogram.filters import Command, CommandStart
from datetime import datetime, timedelta
import asyncio

API_TOKEN = ''
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
state_router = Router()
dp.include_router(state_router)

# Подключение к БД
conn = sqlite3.connect('laundry.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE, count INTEGER DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS schedule (id TEXT, day TEXT, time TEXT, username TEXT, PRIMARY KEY (day, time, username))''')
conn.commit()

# States
class FormState(StatesGroup):
    get_username = State()
    record_day = State()
    record_time = State()


async def reset_schedule():
    while True:
        now = datetime.now()
        if now.weekday() == 0 and now.hour == 0:
            c.execute("DELETE FROM schedule")
            conn.commit()
        await asyncio.sleep(3600)

@state_router.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    existing_username = c.fetchone()
    if existing_username:
        return await message.reply("Вы уже зарегистрированы с никнеймом: " + existing_username[0])

    await state.set_state(FormState.get_username)
    await message.reply("Введите никнейм (номер комнаты и по одной буквы из ФИО, например 777АМР):")

@state_router.message(FormState.get_username)
async def process_username(message: types.Message, state: FSMContext):
    match = re.match(r'^\d{3}[А-Я]{3}$', message.text)
    if match:
        username = message.text
        await state.update_data(username=username)
        await add_user_to_db(username, message.from_user.id)
        await state.set_state(FormState.record_day)
        await choose_day(message)
    else:
        await message.reply("Неправильный формат. Три цифры и три русские буквы.")

async def add_user_to_db(username, uid: int=0):
    c.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (int(uid),username,))
    conn.commit()

async def choose_day(message: types.Message):
    days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    row = [types.KeyboardButton(text=item) for item in days]
    key = types.ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True)
    await message.answer(
        text="Выберите день недели:",
        reply_markup=key
    )


@state_router.message(FormState.record_day)
async def process_day(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    username = user_data.get('username')
    if not username:
        return await message.reply("Для начала задайте имя (/start)")
    day = message.text

    available_times = await get_available_times(day)
    if not available_times:
        await message.reply("Нет доступных временных слотов. Выберите другой день.")
        return await choose_day(message)

    await state.update_data(day=day)
    await state.set_state(FormState.record_time)

    row = [types.KeyboardButton(text=item) for item in available_times]
    key = types.ReplyKeyboardMarkup(keyboard=[row], one_time_keyboard=True, resize_keyboard=True)
    await message.answer(
        text="Выберите время (доступные временные слоты):",
        reply_markup=key
    )

async def get_available_times(day):
    now = datetime.now()
    current_weekday = now.weekday()
    current_time = now.strftime("%H:%M")

    all_times = [f"{hour}:{minute:02}" for hour in range(14, 23) for minute in range(0, 60, 30)]

    day_mapping = {'пн': 0, 'вт': 1, 'ср': 2, 'чт': 3, 'пт': 4, 'сб': 5, 'вс': 6}
    selected_weekday = day_mapping.get(day.lower())

    if selected_weekday == current_weekday:
        all_times = [time for time in all_times if time > current_time]

    c.execute("SELECT time FROM schedule WHERE day=?", (day,))
    booked = {row[0] for row in c.fetchall()}

    return [time for time in all_times if time not in booked]


@state_router.message(FormState.record_time)
async def process_time(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    username = user_data.get('username')
    if not username:
        return await message.reply("Задайте имя (/start)")
    day = user_data.get('day')
    time = message.text

    c.execute("INSERT INTO schedule (day, time, username) VALUES (?, ?, ?)", (day, time, username))
    c.execute("UPDATE users SET count = count + 1 WHERE username=?", (username,))
    conn.commit()

    markup = types.ReplyKeyboardRemove()
    await message.reply("Запись подтверждена!", reply_markup=markup)
    await state.clear()


@state_router.message(FormState.record_time, F.text.lower().contains("назад"))
async def go_back_to_day(message: types.Message, state: FSMContext):
    await state.set_state(FormState.record_day)
    await choose_day(message)


@state_router.message(Command(commands=["set_time"]))
async def select_day(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    c.execute("SELECT username, count FROM users WHERE id=?", (user_id,))
    result = c.fetchone()

    if not result:
        await message.reply("Вы не зарегистрированы. Запустите /start для регистрации.")
        return

    username, count = result
    if count >= 1:
        return await message.reply("Вы уже записались на эту неделю. Вы можете записаться снова в понедельник.")

    await state.update_data(username=username)
    await state.set_state(FormState.record_day)
    await choose_day(message)

@state_router.message(Command(commands=["change"]))
async def change_record(message: types.Message, state: FSMContext):
    # Здесь нужно реализовать логику изменения записи
     await message.reply("Эта функция пока не реализована.")


async def show_schedule_for_day(message: types.Message, day):
    c.execute("SELECT time, username FROM schedule WHERE day=?", (day,))
    schedule = c.fetchall()

    if schedule:
        schedule_text = "\n".join([f"{time}: {username}" for time, username in schedule])
        await message.answer(f"Расписание на {day}:\n{schedule_text}")
    else:
        await message.answer(f"На {day} пока нет записей.")


@state_router.message(Command(commands=["schedule"]))
async def show_schedule(message: types.Message):
    day_names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    for day_name in day_names:
        await show_schedule_for_day(message, day_name)


async def main():
    asyncio.create_task(reset_schedule())
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())