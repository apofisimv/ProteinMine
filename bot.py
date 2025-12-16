import os
import random
import time
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Database connection (use path relative to this file, works on Windows/Linux)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "proteinmine.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

def init_db():
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            drop_type TEXT NOT NULL,
            value INTEGER,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
API_TOKEN = "7101622767:AAFNp4Lpi26rDCpabWIZgSqL-M6ECnkEew0"
# API_TOKEN = "8504100526:AAH1nuyt9TBzZgif8HLxSl1CaMCyXCsJYHo"
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

user_data = {}
MAX_ENERGY = 50
ENERGY_REGEN_TIME = 30
BOOST_COST = 100
BOOST_DURATION = 600
BOOST_MULTIPLIER = 2

def get_or_create_stats(user_id: int):
    cursor.execute("SELECT total_clicks, rare_drops, best_combo FROM stats WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO stats (user_id, total_clicks, rare_drops, best_combo) VALUES (?, 0, 0, 0)", (user_id,))
        conn.commit()
        return {"total_clicks": 0, "rare_drops": 0, "best_combo": 0}
    return {"total_clicks": row[0], "rare_drops": row[1], "best_combo": row[2]}

def get_or_create_user_row(user_id: int):
    cursor.execute("SELECT protein, energy, xp, level, last_daily, daily_streak FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return {"protein": 0, "energy": MAX_ENERGY, "xp": 0, "level": 1, "last_daily": None, "daily_streak": 0}
    return {"protein": row[0], "energy": row[1], "xp": row[2], "level": row[3], "last_daily": row[4], "daily_streak": row[5]}

def save_user_to_db(user_id: int, user_dict: dict):
    cursor.execute("UPDATE users SET protein = ?, energy = ?, xp = ?, level = ? WHERE user_id = ?",
        (user_dict["balance"], user_dict["energy"], user_dict["xp"], user_dict["level"], user_id))
    conn.commit()

def save_daily_info(user_id: int, last_daily: str, daily_streak: int, balance: int):
    cursor.execute("UPDATE users SET last_daily = ?, daily_streak = ?, protein = ? WHERE user_id = ?",
        (last_daily, daily_streak, balance, user_id))
    conn.commit()

def add_drop(user_id: int, drop_type: str, value: int | None):
    cursor.execute("INSERT INTO drops (user_id, drop_type, value) VALUES (?, ?, ?)", (user_id, drop_type, value))
    conn.commit()
    stats = get_or_create_stats(user_id)
    stats["rare_drops"] += 1
    cursor.execute("UPDATE stats SET rare_drops = ? WHERE user_id = ?", (stats["rare_drops"], user_id))
    conn.commit()

def inc_click(user_id: int):
    stats = get_or_create_stats(user_id)
    stats["total_clicks"] += 1
    cursor.execute("UPDATE stats SET total_clicks = ? WHERE user_id = ?", (stats["total_clicks"], user_id))
    conn.commit()

def get_user(user_id: int):
    if user_id not in user_data:
        row = get_or_create_user_row(user_id)
        user_data[user_id] = {
            "balance": row["protein"],
            "xp": row["xp"],
            "level": row["level"],
            "energy": row["energy"],
            "last_energy_ts": time.time(),
            "boost_until": 0,
            "min_gain": 1,
            "max_gain": 5,
        }
    else:
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

BTN_MINE = "🚀 Mine"
BTN_BOOST = "⚡ Boost"
keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
keyboard.add(KeyboardButton(BTN_MINE), KeyboardButton(BTN_BOOST))

# ============================
# REFERRAL SYSTEM
# ============================

@dp.message_handler(commands=["referral", "ref"])
async def cmd_referral(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT referral_count FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    ref_count = row[0] if row else 0
    bot_username = (await bot.me).username
    ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    text = (
        "🎁 <b>REFERRAL PROGRAM</b>\n\n"
        f"👥 Your referrals: <b>{ref_count}</b>\n\n"
        "🎯 <b>Rewards:</b>\n"
        "• Friend gets +100 protein bonus\n"
        "• You get +50 protein per referral\n"
        "• Every 10 referrals = 1 RARE drop guaranteed!\n\n"
        f"🔗 Your link:\n<code>{ref_link}</code>\n\n"
        "Share with friends to earn more!"
    )
    await message.answer(text, parse_mode="HTML")

# ============================
# FRIENDS SYSTEM
# ============================

@dp.message_handler(commands=["friends", "leaderboard"])
async def cmd_friends(message: types.Message):
    user_id = message.from_user.id
    
    cursor.execute("""
        SELECT u.user_id, u.protein, u.level, u.xp
        FROM friendships f
        JOIN users u ON (f.friend_id = u.user_id)
        WHERE f.user_id = ?
        ORDER BY u.protein DESC
        LIMIT 10
    """, (user_id,))
    
    friends = cursor.fetchall()
    
    if not friends:
        await message.answer(
            "👥 <b>FRIENDS LEADERBOARD</b>\n\n"
            "You have no friends added yet!\n\n"
            "Invite friends with /referral and they'll automatically appear here.",
            parse_mode="HTML"
        )
        return
    
    cursor.execute("SELECT protein, level FROM users WHERE user_id = ?", (user_id,))
    my_data = cursor.fetchone()
    my_protein = my_data[0] if my_data else 0
    
    text = ["👥 <b>FRIENDS LEADERBOARD</b>\n"]
    
    for i, (fid, protein, level, xp) in enumerate(friends, start=1):
        try:
            friend = await bot.get_chat(fid)
            name = friend.first_name
        except:
            name = f"User {fid}"
        
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        
        if fid == user_id:
            text.append(f"{medal} <b>YOU</b> - {protein} 🧬 (Lv {level})")
        else:
            diff = my_protein - protein
            if diff > 0:
                text.append(f"{medal} {name} - {protein} 🧬 (🔻 {diff} behind you)")
            elif diff < 0:
                text.append(f"{medal} {name} - {protein} 🧬 (🔺 {abs(diff)} ahead)")
            else:
                text.append(f"{medal} {name} - {protein} 🧬")
    
    text.append("\n\n💡 Invite more friends to compete!")
    await message.answer("\n".join(text), parse_mode="HTML")

@dp.message_handler(commands=["addfriend"])
async def cmd_add_friend(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT referred_id FROM referrals WHERE referrer_id = ?", (user_id,))
    referrals = cursor.fetchall()
    added = 0
    
    for (friend_id,) in referrals:
        try:
            cursor.execute("INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)", (user_id, friend_id))
            cursor.execute("INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)", (friend_id, user_id))
            added += 1
        except:
            pass
    
    conn.commit()
    await message.answer(f"✅ Added {added} friends from your referrals!\nUse /friends to see leaderboard.")

# ============================
# CLAN SYSTEM
# ============================

@dp.message_handler(commands=["clan"])
async def cmd_clan(message: types.Message):
    user_id = message.from_user.id
    
    cursor.execute("SELECT clan_id, clan_contribution FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row and row[0]:
        clan_id = row[0]
        contribution = row[1]
        
        cursor.execute("SELECT name, total_protein, members_count FROM clans WHERE id = ?", (clan_id,))
        clan = cursor.fetchone()
        
        if clan:
            text = (
                f"🏰 <b>Your Clan: {clan[0]}</b>\n\n"
                f"🧬 Total Protein: <b>{clan[1]}</b>\n"
                f"👥 Members: <b>{clan[2]}</b>\n"
                f"🎯 Your Contribution: <b>{contribution}</b>\n\n"
                "Use /clan_top to see clan leaderboard!"
            )
            await message.answer(text, parse_mode="HTML")
    else:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        
        keyboard = InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            InlineKeyboardButton("🏛️ Ankara", callback_data="clan:1"),
            InlineKeyboardButton("🌉 Istanbul", callback_data="clan:2")
        )
        keyboard.add(
            InlineKeyboardButton("🏖️ Izmir", callback_data="clan:3"),
            InlineKeyboardButton("🏔️ Antalya", callback_data="clan:4")
        )
        keyboard.add(InlineKeyboardButton("🏙️ Bursa", callback_data="clan:5"))
        
        await message.answer(
            "🏰 <b>Choose Your Clan!</b>\n\n"
            "Join one of the Turkish clans and compete for glory!\n"
            "Your mining will contribute to your clan's total.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('clan:'))
async def process_clan_choice(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    clan_id = int(callback_query.data.split(':')[1])
    
    cursor.execute("SELECT clan_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row and row[0]:
        await callback_query.answer("You already have a clan!", show_alert=True)
        return
    
    cursor.execute("UPDATE users SET clan_id = ? WHERE user_id = ?", (clan_id, user_id))
    cursor.execute("UPDATE clans SET members_count = members_count + 1 WHERE id = ?", (clan_id,))
    conn.commit()
    
    cursor.execute("SELECT name FROM clans WHERE id = ?", (clan_id,))
    clan_name = cursor.fetchone()[0]
    
    await callback_query.message.edit_text(
        f"🎉 Welcome to <b>{clan_name}</b>!\n\n"
        "Your mining now contributes to your clan.\n"
        "Use /clan to see clan info!",
        parse_mode="HTML"
    )
    await callback_query.answer()

@dp.message_handler(commands=["clan_top", "clans"])
async def cmd_clan_top(message: types.Message):
    cursor.execute("SELECT name, total_protein, members_count FROM clans ORDER BY total_protein DESC LIMIT 10")
    rows = cursor.fetchall()
    
    if not rows:
        await message.answer("No clans yet.")
        return
    
    text = ["🏆 <b>CLAN LEADERBOARD</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    
    for i, (name, protein, members) in enumerate(rows, start=1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text.append(f"{medal} <b>{name}</b>")
        text.append(f"   🧬 {protein:,} protein | 👥 {members} members\n")
    
    await message.answer("\n".join(text), parse_mode="HTML")

# ============================
# START COMMAND
# ============================

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args()
    
    if args and args.startswith("ref"):
        try:
            referrer_id = int(args[3:])
            if referrer_id != user_id:
                cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,))
                existing = cursor.fetchone()
                
                if existing is None or existing[0] is None:
                    cursor.execute("INSERT OR REPLACE INTO users (user_id, protein, referrer_id) VALUES (?, 100, ?)", (user_id, referrer_id))
                    cursor.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, user_id))
                    cursor.execute("UPDATE users SET referral_count = referral_count + 1, protein = protein + 50 WHERE user_id = ?", (referrer_id,))
                    conn.commit()
                    
                    # Auto-add as friends
                    try:
                        cursor.execute("INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)", (referrer_id, user_id))
                        cursor.execute("INSERT OR IGNORE INTO friendships (user_id, friend_id) VALUES (?, ?)", (user_id, referrer_id))
                        conn.commit()
                    except:
                        pass
                    
                    try:
                        ref_count = cursor.execute('SELECT referral_count FROM users WHERE user_id = ?', (referrer_id,)).fetchone()[0]
                        await bot.send_message(referrer_id, f"🎉 New referral! +50 protein bonus!\nTotal referrals: {ref_count}")
                    except:
                        pass
                    
                    await message.answer("🎁 Welcome! You got +100 protein bonus from referral!\nStart mining now! 🚀", parse_mode="HTML")
        except:
            pass
    
    get_user(user_id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    webapp = InlineKeyboardMarkup(row_width=1)
    webapp.add(InlineKeyboardButton("🎮 PLAY GAME", web_app=WebAppInfo(url="https://unresilient-autonomically-julia.ngrok-free.dev?v=4")))
    await message.answer("🧬 <b>ProteinMine!</b>\n\n🎮 Tap button to play!", reply_markup=webapp, parse_mode="HTML")
    await message.answer("Or use buttons below:", reply_markup=keyboard, parse_mode="HTML")

# ============================
# OTHER COMMANDS
# ============================

@dp.message_handler(commands=["profile"])
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    cursor.execute("SELECT protein, energy, xp, level, last_daily, daily_streak FROM users WHERE user_id = ?", (user_id,))
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
    cursor.execute("SELECT protein, last_daily, daily_streak FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
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
    
    if last_date == now:
        await message.answer("🕒 You already claimed your daily reward today. Come back tomorrow!")
        return
    
    if last_date == (now.replace(day=now.day - 1) if now.day > 1 else None):
        daily_streak += 1
    else:
        daily_streak = 1
    
    base_reward = random.randint(20, 50)
    bonus_multiplier = 1 + (daily_streak - 1) * 0.1
    reward = int(base_reward * bonus_multiplier)
    balance += reward
    
    save_daily_info(user_id, datetime.utcnow().isoformat(), daily_streak, balance)
    
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
    
    if user.get("boost_until", 0) > now:
        remaining = int(user["boost_until"] - now)
        minutes = remaining // 60
        seconds = remaining % 60
        await message.answer(f"⚡ Boost already active!\nRemaining: {minutes} min {seconds} sec.")
        return
    
    if user["balance"] < BOOST_COST:
        await message.answer(f"Not enough protein for boost.\nNeed: {BOOST_COST}, you have: {user['balance']}.")
        return
    
    user["balance"] -= BOOST_COST
    user["boost_until"] = now + BOOST_DURATION
    save_user_to_db(user_id, user)
    
    await message.answer(f"⚡ BOOST X{BOOST_MULTIPLIER} ACTIVATED!\nDuration: {BOOST_DURATION // 60} minutes.\nCost: {BOOST_COST} protein.")

@dp.message_handler(lambda m: m.text == BTN_BOOST)
async def btn_boost(message: types.Message):
    await cmd_boost(message)

@dp.message_handler(commands=["upgrade"])
async def cmd_upgrade(message: types.Message):
    text = (
        "🧬 <b>UPGRADES MENU</b>\n\n"
        "1️⃣ <b>+1 Min Gain</b> — 200 protein (/upgrade_min)\n"
        "2️⃣ <b>+1 Max Gain</b> — 300 protein (/upgrade_max)\n\n"
        "Choose an upgrade."
    )
    await message.answer(text, parse_mode="HTML")

@dp.message_handler(commands=["upgrade_min"])
async def upgrade_min(message: types.Message):
    user = get_user(message.from_user.id)
    cost = 200
    
    if user["balance"] < cost:
        return await message.answer("Not enough protein for this upgrade.")
    
    user["balance"] -= cost
    user["min_gain"] += 1
    await message.answer(f"🔧 Min drop increased! Now: {user['min_gain']}–{user['max_gain']} PROTEIN.")

@dp.message_handler(commands=["upgrade_max"])
async def upgrade_max(message: types.Message):
    user = get_user(message.from_user.id)
    cost = 300
    
    if user["balance"] < cost:
        return await message.answer("Not enough protein for this upgrade.")
    
    user["balance"] -= cost
    user["max_gain"] += 1
    await message.answer(f"🔧 Max drop increased! Now: {user['min_gain']}–{user['max_gain']} PROTEIN.")

@dp.message_handler(lambda m: m.text == BTN_MINE)
async def mine(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    regenerate_energy(user)
    
    if user["energy"] <= 0:
        await message.answer("⚡ Energy is empty!\nWait for regeneration…")
        return
    
    user["energy"] -= 1
    inc_click(user_id)
    
    roll = random.random()
    if roll < 0.001:
        rarity = "LEGENDARY"
        emoji = "💎"
        multiplier = 100
    elif roll < 0.01:
        rarity = "EPIC"
        emoji = "🔮"
        multiplier = 20
    elif roll < 0.10:
        rarity = "RARE"
        emoji = "⭐"
        multiplier = 5
    else:
        rarity = "COMMON"
        emoji = "🧬"
        multiplier = 1
    
    base_gain = random.randint(user["min_gain"], user["max_gain"])
    now = time.time()
    boost_active = user.get("boost_until", 0) > now
    
    if boost_active:
        gained = base_gain * multiplier * BOOST_MULTIPLIER
        boost_text = "⚡ BOOST x2\n"
    else:
        gained = base_gain * multiplier
        boost_text = ""
    
    user["balance"] += gained
    user["xp"] += gained
    
    if rarity != "COMMON":
        add_drop(user_id, rarity, gained)
    
    if user["xp"] >= user["level"] * 100:
        user["level"] += 1
        user["xp"] = 0
        levelup_text = "\n🔥 LEVEL UP!"
    else:
        levelup_text = ""
    
    save_user_to_db(user_id, user)
    
    # Update clan contribution
    cursor.execute("SELECT clan_id FROM users WHERE user_id = ?", (user_id,))
    clan_row = cursor.fetchone()
    if clan_row and clan_row[0]:
        cursor.execute("UPDATE users SET clan_contribution = clan_contribution + ? WHERE user_id = ?", (gained, user_id))
        cursor.execute("UPDATE clans SET total_protein = total_protein + ? WHERE id = ?", (gained, clan_row[0]))
        conn.commit()
    
    if rarity == "LEGENDARY":
        msg = f"{'='*30}\n💎💎💎 LEGENDARY PROTEIN! 💎💎💎\n{'='*30}\n+{gained} PROTEIN (x{multiplier})\n🎉 THIS IS ULTRA RARE! 🎉\n"
    elif rarity == "EPIC":
        msg = f"{'='*25}\n🔮🔮 EPIC PROTEIN! 🔮🔮\n{'='*25}\n+{gained} PROTEIN (x{multiplier})\n⚡ RARE DROP!\n"
    elif rarity == "RARE":
        msg = f"⭐ RARE PROTEIN!\n+{gained} PROTEIN (x{multiplier})\n"
    else:
        msg = f"{emoji} +{gained} PROTEIN\n"
    
    msg += f"{boost_text}\n💰 Balance: {user['balance']}\n📊 XP: {user['xp']}\n⭐ Level: {user['level']}\n⚡ Energy: {user['energy']}/{MAX_ENERGY}{levelup_text}"
    await message.answer(msg)

@dp.message_handler(commands=["top"])
async def cmd_top(message: types.Message):
    cursor.execute("SELECT user_id, protein FROM users ORDER BY protein DESC LIMIT 20")
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

if __name__ == "__main__":
    print("ProteinMine bot is running with ALL FEATURES...")
    executor.start_polling(dp, skip_updates=True)
