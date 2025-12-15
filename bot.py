import os
import random
import time
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# ============================
# SQLite DATABASE
# ============================

# Один общий коннект
conn = sqlite3.connect("/opt/proteinmine/proteinmine.db", check_same_thread=False)
cursor = conn.cursor()


def init_db():
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            protein INTEGER DEFAULT 0,
            energy INTEGER DEFAULT 50,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_daily TEXT DEFAULT NULL,
            daily_streak INTEGER DEFAULT 0
        )
    """)

    # Таблица для редких бонусов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            drop_type TEXT NOT NULL,
            value INTEGER,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица статистики
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            total_clicks INTEGER DEFAULT 0,
            rare_drops INTEGER DEFAULT 0,
            best_combo INTEGER DEFAULT 0
        )
    """)

    conn.commit()


init_db()

# ============================
# BOT CONFIG
# ============================

API_TOKEN = "8504100526:AAH1nuyt9TBzZgif8HLxSl1CaMCyXCsJYHo"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ============================
# IN-MEMORY USER CACHE
# ============================

user_data = {}  # user_id -> dict

MAX_ENERGY = 50
ENERGY_REGEN_TIME = 30  # +1 energy каждые 30 секунд

# BOOST SETTINGS
BOOST_COST = 100        # сколько protein стоит включить буст
BOOST_DURATION = 600    # длительность буста в секундах (600 = 10 минут)
BOOST_MULTIPLIER = 2    # во сколько раз умножаем добычу


def get_or_create_stats(user_id: int):
    cursor.execute("SELECT total_clicks, rare_drops, best_combo FROM stats WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO stats (user_id, total_clicks, rare_drops, best_combo) VALUES (?, 0, 0, 0)",
            (user_id,)
        )
        conn.commit()
        return {"total_clicks": 0, "rare_drops": 0, "best_combo": 0}
    return {"total_clicks": row[0], "rare_drops": row[1], "best_combo": row[2]}


def get_or_create_user_row(user_id: int):
    """
    Берём пользователя из БД.
    Если нет — создаём с дефолтами.
    """
    cursor.execute(
        "SELECT protein, energy, xp, level, last_daily, daily_streak FROM users WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return {
            "protein": 0,
            "energy": MAX_ENERGY,
            "xp": 0,
            "level": 1,
            "last_daily": None,
            "daily_streak": 0,
        }

    return {
        "protein": row[0],
        "energy": row[1],
        "xp": row[2],
        "level": row[3],
        "last_daily": row[4],
        "daily_streak": row[5],
    }


def save_user_to_db(user_id: int, user_dict: dict):
    cursor.execute(
        """
        UPDATE users
        SET protein = ?, energy = ?, xp = ?, level = ?
        WHERE user_id = ?
        """,
        (
            user_dict["balance"],
            user_dict["energy"],
            user_dict["xp"],
            user_dict["level"],
            user_id,
        ),
    )
    conn.commit()


def save_daily_info(user_id: int, last_daily: str, daily_streak: int, balance: int):
    cursor.execute(
        """
        UPDATE users
        SET last_daily = ?, daily_streak = ?, protein = ?
        WHERE user_id = ?
        """,
        (last_daily, daily_streak, balance, user_id),
    )
    conn.commit()


def add_drop(user_id: int, drop_type: str, value: int | None):
    cursor.execute(
        "INSERT INTO drops (user_id, drop_type, value) VALUES (?, ?, ?)",
        (user_id, drop_type, value),
    )
    conn.commit()

    # Обновляем счётчик редких дропов
    stats = get_or_create_stats(user_id)
    stats["rare_drops"] += 1
    cursor.execute(
        "UPDATE stats SET rare_drops = ? WHERE user_id = ?",
        (stats["rare_drops"], user_id),
    )
    conn.commit()


def inc_click(user_id: int):
    stats = get_or_create_stats(user_id)
    stats["total_clicks"] += 1
    cursor.execute(
        "UPDATE stats SET total_clicks = ? WHERE user_id = ?",
        (stats["total_clicks"], user_id),
    )
    conn.commit()

def get_user(user_id: int):
    """
    Возвращает user_dict из кэша.
    Если нет — грузит из базы и кладёт в кэш.
    """
    if user_id not in user_data:
        row = get_or_create_user_row(user_id)
        user_data[user_id] = {
            "balance": row["protein"],
            "xp": row["xp"],
            "level": row["level"],
            "energy": row["energy"],
            "last_energy_ts": time.time(),
            "boost_until": 0,

            # базовые значения апгрейдов
            "min_gain": 1,   # минимальный дроп
            "max_gain": 5,   # максимальный дроп
        }
    else:
        # на всякий случай, если в старом кэше нет этих полей
        if "boost_until" not in user_data[user_id]:
            user_data[user_id]["boost_until"] = 0
        if "min_gain" not in user_data[user_id]:
            user_data[user_id]["min_gain"] = 1
        if "max_gain" not in user_data[user_id]:
            user_data[user_id]["max_gain"] = 5

    return user_data[user_id]



def regenerate_energy(user: dict):
    now = time.time()
    elapsed = now - user["last_energy_ts"]
    regen_points = int(elapsed // ENERGY_REGEN_TIME)

    if regen_points > 0:
        user["energy"] = min(MAX_ENERGY, user["energy"] + regen_points)
        user["last_energy_ts"] = now


# ============================
# KEYBOARD
# ============================

BTN_MINE = "🚀 Mine"
BTN_BOOST = "⚡ Boost"

keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
keyboard.add(KeyboardButton(BTN_MINE), KeyboardButton(BTN_BOOST))


# ============================
# HANDLERS
# ============================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    get_user(user_id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    webapp = InlineKeyboardMarkup(row_width=1)
    webapp.add(InlineKeyboardButton("🎮 PLAY GAME", web_app=WebAppInfo(url="https://unresilient-autonomically-julia.ngrok-free.dev?v=2")))
    await message.answer("🧬 <b>ProteinMine!</b>\n\n🎮 Tap button to play!", reply_markup=webapp, parse_mode="HTML")
    await message.answer("Or use buttons below:", reply_markup=keyboard, parse_mode="HTML")

@dp.message_handler(commands=["profile"])
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id

    # Данные из БД
    cursor.execute(
        "SELECT protein, energy, xp, level, last_daily, daily_streak FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        await message.answer("You have no profile yet. Tap 🚀 Mine to begin.")
        return

    protein, energy, xp, level, last_daily, daily_streak = row

    stats = get_or_create_stats(user_id)

    text_lines = [
        f"👤 Profile of <b>{message.from_user.full_name}</b>",
        "",
        f"🧬 Protein: <b>{protein}</b>",
        f"⭐ Level: <b>{level}</b>",
        f"📈 XP: <b>{xp}</b>",
        f"⚡ Energy: <b>{energy}/{MAX_ENERGY}</b>",
        "",
        f"🖱 Total clicks: <b>{stats['total_clicks']}</b>",
        f"🌟 Rare drops: <b>{stats['rare_drops']}</b>",
        f"🔥 Best combo: <b>{stats['best_combo']}</b>",
    ]

    if last_daily:
        text_lines.append("")
        text_lines.append(f"🎁 Daily streak: <b>{daily_streak}</b>")

    await message.answer("\n".join(text_lines), parse_mode="HTML")


@dp.message_handler(commands=["daily"])
async def cmd_daily(message: types.Message):
    user_id = message.from_user.id

    # Берём текущие данные пользователя
    cursor.execute(
        "SELECT protein, last_daily, daily_streak FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if row is None:
        # Создаём пользователя, если его ещё нет
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        balance = 0
        last_daily = None
        daily_streak = 0
    else:
        balance, last_daily, daily_streak = row

    now = datetime.utcnow().date()

    if last_daily is not None:
        try:
            last_date = datetime.fromisoformat(last_daily).date()
        except ValueError:
            last_date = None
    else:
        last_date = None

    # Уже сегодня получал
    if last_date == now:
        await message.answer("🕒 You already claimed your daily reward today. Come back tomorrow!")
        return

    # Проверяем стрик
    if last_date == (now.replace(day=now.day - 1) if now.day > 1 else None):
        # Вчера забирал → продолжаем стрик
        daily_streak += 1
    else:
        # Стрик сброшен
        daily_streak = 1

    base_reward = random.randint(20, 50)
    bonus_multiplier = 1 + (daily_streak - 1) * 0.1  # +10% за каждый день стрика
    reward = int(base_reward * bonus_multiplier)

    balance += reward
    save_daily_info(user_id, datetime.utcnow().isoformat(), daily_streak, balance)

    # Обновим кэш, если игрок уже майнил
    if user_id in user_data:
        user_data[user_id]["balance"] = balance

    text = (
        "🎁 <b>DAILY REWARD</b>\n"
        f"+<b>{reward}</b> protein\n\n"
        f"🔥 Streak: <b>{daily_streak}</b> day(s)\n"
        "Come back tomorrow!"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message_handler(commands=["boost"])
async def cmd_boost(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    now = time.time()

    # если уже активен
    if user.get("boost_until", 0) > now:
        remaining = int(user["boost_until"] - now)
        minutes = remaining // 60
        seconds = remaining % 60
        await message.answer(
            f"⚡ Boost уже активен!\n"
            f"Осталось: {minutes} мин {seconds} сек."
        )
        return

    # проверяем баланс
    if user["balance"] < BOOST_COST:
        await message.answer(
            f"Недостаточно protein для буста.\n"
            f"Нужно: {BOOST_COST}, у тебя: {user['balance']}."
        )
        return

    # включаем буст
    user["balance"] -= BOOST_COST
    user["boost_until"] = now + BOOST_DURATION

    # сохраняем баланс
    save_user_to_db(user_id, user)

    await message.answer(
        f"⚡ BOOST X{BOOST_MULTIPLIER} АКТИВИРОВАН!\n"
        f"Длительность: {BOOST_DURATION // 60} минут.\n"
        f"Списано: {BOOST_COST} protein."
    )


@dp.message_handler(lambda m: m.text == BTN_BOOST)
async def btn_boost(message: types.Message):
    await cmd_boost(message)

@dp.message_handler(commands=["upgrade"])
async def cmd_upgrade(message: types.Message):
    user = get_user(message.from_user.id)

    text = (
        "🧬 <b>UPGRADES MENU</b>\n\n"
        "1️⃣ <b>+1 Min Gain</b> — 200 protein (/upgrade_min)\n"
        "2️⃣ <b>+1 Max Gain</b> — 300 protein (/upgrade_max)\n\n"
        "Выбери апгрейд командой."
    )

    await message.answer(text, parse_mode="HTML")
@dp.message_handler(commands=["upgrade_min"])
async def upgrade_min(message: types.Message):
    user = get_user(message.from_user.id)

    cost = 200
    if user["balance"] < cost:
        return await message.answer("Не хватает protein для этого улучшения.")

    user["balance"] -= cost
    user["min_gain"] += 1

    await message.answer(
        f"🔧 Минимальный дроп увеличен! Теперь: {user['min_gain']}–{user['max_gain']} PROTEIN."
    )
@dp.message_handler(commands=["upgrade_max"])
async def upgrade_max(message: types.Message):
    user = get_user(message.from_user.id)

    cost = 300
    if user["balance"] < cost:
        return await message.answer("Не хватает protein для этого улучшения.")

    user["balance"] -= cost
    user["max_gain"] += 1

    await message.answer(
        f"🔧 Максимальный дроп увеличен! Теперь: {user['min_gain']}–{user['max_gain']} PROTEIN."
    )


@dp.message_handler(lambda m: m.text == BTN_MINE)
async def mine(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)

    # Реген энергии
    regenerate_energy(user)

    if user["energy"] <= 0:
        await message.answer("⚡ Energy is empty!\nWait for regeneration…")
        return

    user["energy"] -= 1
    inc_click(user_id)


    # обычный майнинг + учёт буста
    base_gain = random.randint(user["min_gain"], user["max_gain"])

    now = time.time()
    boost_active = user.get("boost_until", 0) > now

    if boost_active:
        gained = base_gain * BOOST_MULTIPLIER
        boost_text = "⚡ BOOST x2 ACTIVE\n"
    else:
        gained = base_gain
        boost_text = ""

    user["balance"] += gained
    user["xp"] += gained


    rare_text = ""  # текст сообщения о редком бонусе
    got_rare = False

    # ================================
    # 🎁 РЕДКИЕ БОНУСЫ
    # ================================
    roll = random.random()

    # 10% шанс — Protein Burst (+50–200)
    if roll < 0.10:
        burst = random.randint(50, 200)
        user["balance"] += burst
        rare_text = f"🌟 RARE DROP!\nProtein Burst +{burst}\n"
        add_drop(user_id, "Protein Burst", burst)
        got_rare = True

    # 2% шанс — Energy Refill
    elif roll < 0.12:
        user["energy"] = MAX_ENERGY
        rare_text = "⚡ RARE DROP!\nFull Energy Refill!\n"
        add_drop(user_id, "Energy Refill", None)
        got_rare = True

    # 1% шанс — Crystal Sample
    elif roll < 0.13:
        rare_text = "💠 ULTRA DROP!\nCrystal Sample acquired!\n"
        add_drop(user_id, "Crystal Sample", None)
        got_rare = True

    # 0.05% шанс — Rare Gene
    elif roll < 0.1305:
        rare_text = "🧬 LEGENDARY DROP!\nRARE GENE FOUND!\n"
        add_drop(user_id, "Rare Gene", None)
        got_rare = True

    # Level up
    if user["xp"] >= user["level"] * 10:
        user["level"] += 1
        user["xp"] = 0
        levelup_text = "🔥 LEVEL UP! Congratulations!"
    else:
        levelup_text = ""

    # Сохраняем в базу
    save_user_to_db(user_id, user)

    await message.answer(
        f"{boost_text}"
        f"+{gained} PROTEIN\n"
        f"{rare_text}"
        f"Balance: {user['balance']}\n"
        f"XP: {user['xp']}\n"
        f"Level: {user['level']}\n"
        f"⚡ Energy: {user['energy']}/{MAX_ENERGY}\n"
        f"{levelup_text}"
    )


# ============================
# START BOT
# ============================

@dp.message_handler(commands=["top"])
async def cmd_top(message: types.Message):
    cursor.execute("""
        SELECT user_id, protein FROM users
        ORDER BY protein DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()

    if not rows:
        await message.answer("Leaderboard is empty.")
        return

    text = ["🏆 <b>GLOBAL PROTEIN LEADERBOARD</b>\n"]

    for i, (uid, protein) in enumerate(rows, start=1):
        try:
            user = await bot.get_chat(uid)
            name = user.full_name
        except:
            name = f"User {uid}"

        text.append(f"{i}. <b>{name}</b> — {protein} protein")

    await message.answer("\n".join(text), parse_mode="HTML")
@dp.message_handler(commands=["top_clicks"])
async def cmd_top_clicks(message: types.Message):
    cursor.execute("""
        SELECT user_id, total_clicks FROM stats
        ORDER BY total_clicks DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()

    if not rows:
        await message.answer("Click leaderboard is empty.")
        return

    text = ["🖱 <b>TOP CLICKERS</b>\n"]

    for i, (uid, clicks) in enumerate(rows, start=1):
        try:
            user = await bot.get_chat(uid)
            name = user.full_name
        except:
            name = f"User {uid}"

        text.append(f"{i}. <b>{name}</b> — {clicks} clicks")

    await message.answer("\n".join(text), parse_mode="HTML")

@dp.message_handler(commands=["top_level"])
async def cmd_top_level(message: types.Message):
    cursor.execute("""
        SELECT user_id, level, xp FROM users
        ORDER BY level DESC, xp DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()

    if not rows:
        await message.answer("Level leaderboard is empty.")
        return

    text = ["⭐ <b>TOP LEVELS</b>\n"]

    for i, (uid, level, xp) in enumerate(rows, start=1):
        try:
            user = await bot.get_chat(uid)
            name = user.full_name
        except:
            name = f"User {uid}"

        text.append(f"{i}. <b>{name}</b> — Level {level} ({xp} XP)")

    await message.answer("\n".join(text), parse_mode="HTML")

@dp.message_handler(commands=["top_drops"])
async def cmd_top_drops(message: types.Message):
    cursor.execute("""
        SELECT user_id, rare_drops FROM stats
        ORDER BY rare_drops DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()

    if not rows:
        await message.answer("Drop leaderboard is empty.")
        return

    text = ["💠 <b>TOP RARE DROP HUNTERS</b>\n"]

    for i, (uid, drops_count) in enumerate(rows, start=1):
        try:
            user = await bot.get_chat(uid)
            name = user.full_name
        except:
            name = f"User {uid}"

        text.append(f"{i}. <b>{name}</b> — {drops_count} rare drops")

    await message.answer("\n".join(text), parse_mode="HTML")


if __name__ == "__main__":
    print("ProteinMine bot is running with ENERGY + DB + PROFILE + DAILY system...")
    executor.start_polling(dp, skip_updates=True)
