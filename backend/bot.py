import os
import random
import time
from datetime import datetime

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Load environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

from .db import db

# Database is initialized in db.py
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

WEBAPP_URL = os.getenv("PROTEINMINE_WEBAPP_URL")
if not WEBAPP_URL:
    raise RuntimeError("PROTEINMINE_WEBAPP_URL is not set")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

user_data = {}
MAX_ENERGY = 50
ENERGY_REGEN_TIME = 30
BOOST_COST = 100
BOOST_DURATION = 600
BOOST_MULTIPLIER = 2

# Referral rewards (friend & referrer)
REFERRAL_FRIEND_BONUS_PROTEIN = 100
REFERRAL_REFERRER_BONUS_PROTEIN = 50
REFERRAL_REFERRER_BONUS_ENERGY = 20


def get_or_create_stats(user_id: int):
    stats = db.stats.find_one({"user_id": user_id})
    if stats is None:
        stats = {
            "user_id": user_id,
            "total_clicks": 0,
            "rare_drops": 0,
            "best_combo": 0
        }
        db.stats.insert_one(stats)
        return {"total_clicks": 0, "rare_drops": 0, "best_combo": 0}
    return {
        "total_clicks": stats.get("total_clicks", 0),
        "rare_drops": stats.get("rare_drops", 0),
        "best_combo": stats.get("best_combo", 0)
    }


def get_or_create_user_row(user_id: int):
    user = db.users.find_one({"user_id": user_id})
    if user is None:
        user = {
            "user_id": user_id,
            "protein": 0,
            "energy": MAX_ENERGY,
            "xp": 0,
            "level": 1,
            "last_daily": None,
            "daily_streak": 0,
            "clan_id": None,
            "clan_contribution": 0,
            "referrer_id": None,
            "referral_count": 0
        }
        db.users.insert_one(user)
        return {
            "protein": 0,
            "energy": MAX_ENERGY,
            "xp": 0,
            "level": 1,
            "last_daily": None,
            "daily_streak": 0,
        }
    return {
        "protein": user.get("protein", 0),
        "energy": user.get("energy", MAX_ENERGY),
        "xp": user.get("xp", 0),
        "level": user.get("level", 1),
        "last_daily": user.get("last_daily"),
        "daily_streak": user.get("daily_streak", 0),
    }


def save_user_to_db(user_id: int, user_dict: dict):
    db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "protein": user_dict["balance"],
                "energy": user_dict["energy"],
                "xp": user_dict["xp"],
                "level": user_dict["level"]
            }
        }
    )


def save_daily_info(user_id: int, last_daily: str, daily_streak: int, balance: int):
    db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "last_daily": last_daily,
                "daily_streak": daily_streak,
                "protein": balance
            }
        }
    )


def add_drop(user_id: int, drop_type: str, value: int | None):
    from datetime import datetime
    db.drops.insert_one({
        "user_id": user_id,
        "drop_type": drop_type,
        "value": value,
        "timestamp": datetime.utcnow().isoformat()
    })
    stats = get_or_create_stats(user_id)
    stats["rare_drops"] += 1
    db.stats.update_one(
        {"user_id": user_id},
        {"$set": {"rare_drops": stats["rare_drops"]}}
    )


def inc_click(user_id: int):
    stats = get_or_create_stats(user_id)
    stats["total_clicks"] += 1
    db.stats.update_one(
        {"user_id": user_id},
        {"$set": {"total_clicks": stats["total_clicks"]}}
    )


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


BTN_MINE = "💎 Focus"
BTN_BOOST = "⚡ Boost"
keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
keyboard.add(KeyboardButton(BTN_MINE), KeyboardButton(BTN_BOOST))


# ============================
# REFERRAL SYSTEM
# ============================


@dp.message_handler(commands=["referral", "ref"])
async def cmd_referral(message: types.Message):
    user_id = message.from_user.id
    user = db.users.find_one({"user_id": user_id})
    ref_count = user.get("referral_count", 0) if user else 0
    bot_username = (await bot.me).username
    ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    text = (
        "🎁 <b>REFERRAL PROGRAM</b>\n\n"
        f"👥 Your referrals: <b>{ref_count}</b>\n\n"
        "🎯 <b>Rewards:</b>\n"
        f"• Friend gets +{REFERRAL_FRIEND_BONUS_PROTEIN} attention bonus\n"
        f"• You get +{REFERRAL_REFERRER_BONUS_PROTEIN} attention and +{REFERRAL_REFERRER_BONUS_ENERGY} desire per referral\n"
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

    friendships = db.friendships.find({"user_id": user_id}).limit(10)
    friend_ids = [f["friend_id"] for f in friendships]

    if not friend_ids:
        await message.answer(
            "👥 <b>WHO SHE NOTICES</b>\n\n"
            "You have no friends added yet.\n\n"
            "Bring someone who would like her.",
            parse_mode="HTML",
        )
        return

    friends = list(db.users.find(
        {"user_id": {"$in": friend_ids}}
    ).sort("protein", -1).limit(10))

    my_user = db.users.find_one({"user_id": user_id})
    my_protein = my_user.get("protein", 0) if my_user else 0

    text = ["👥 <b>FRIENDS LEADERBOARD</b>\n"]

    for i, friend in enumerate(friends, start=1):
        fid = friend["user_id"]
        protein = friend.get("protein", 0)
        level = friend.get("level", 1)
        xp = friend.get("xp", 0)
        
        try:
            friend_chat = await bot.get_chat(fid)
            name = friend_chat.first_name
        except Exception:
            name = f"User {fid}"

        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."

        if fid == user_id:
            text.append(f"{medal} <b>■ YOU</b> - {protein} ATT (Trust Lv {level})")
        else:
            diff = my_protein - protein
            if diff > 0:
                text.append(
                    f"{medal} ■ {name} - {protein} ATT (🔻 {diff} behind you)"
                )
            elif diff < 0:
                text.append(
                    f"{medal} ■ {name} - {protein} ATT (🔺 {abs(diff)} ahead)"
                )
            else:
                text.append(f"{medal} ■ {name} - {protein} ATT")

    text.append("\n\n💡 Bring someone who would like her.")
    await message.answer("\n".join(text), parse_mode="HTML")


@dp.message_handler(commands=["addfriend"])
async def cmd_add_friend(message: types.Message):
    user_id = message.from_user.id
    referrals = db.referrals.find({"referrer_id": user_id})
    added = 0

    for ref in referrals:
        try:
            friend_id = ref["referred_id"]
            # Use update_one with upsert to avoid duplicates
            db.friendships.update_one(
                {"user_id": user_id, "friend_id": friend_id},
                {"$set": {"user_id": user_id, "friend_id": friend_id}},
                upsert=True
            )
            db.friendships.update_one(
                {"user_id": friend_id, "friend_id": user_id},
                {"$set": {"user_id": friend_id, "friend_id": user_id}},
                upsert=True
            )
            added += 1
        except Exception:
            pass

    await message.answer(
        f"✅ Added {added} friends from your referrals!\nUse /friends to see leaderboard."
    )


# ============================
# CLAN SYSTEM
# ============================


@dp.message_handler(commands=["clan"])
async def cmd_clan(message: types.Message):
    user_id = message.from_user.id

    user = db.users.find_one({"user_id": user_id})
    
    if user and user.get("clan_id"):
        clan_id = user["clan_id"]
        contribution = user.get("clan_contribution", 0)

        clan = db.clans.find_one({"id": clan_id})

        if clan:
            text = (
                f"💫 <b>Your Private Circle: {clan['name']}</b>\n\n"
                f"🧬 Total Attention: <b>{clan.get('total_protein', 0)}</b>\n"
                f"👥 Members: <b>{clan.get('members_count', 0)}</b>\n"
                f"🎯 Your Contribution: <b>{contribution}</b>\n\n"
                "Use /clan_top to see circle leaderboard!"
            )
            await message.answer(text, parse_mode="HTML")
    else:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🏛️ Ankara", callback_data="clan:1"),
            InlineKeyboardButton("🌉 Istanbul", callback_data="clan:2"),
        )
        kb.add(
            InlineKeyboardButton("🏖️ Izmir", callback_data="clan:3"),
            InlineKeyboardButton("🏔️ Antalya", callback_data="clan:4"),
        )
        kb.add(InlineKeyboardButton("🏙️ Bursa", callback_data="clan:5"))

        await message.answer(
            "💫 <b>Choose Your Private Circle</b>\n\n"
            "Join a small group. Closer feeling.\n"
            "Your focus will contribute to your circle's total.",
            reply_markup=kb,
            parse_mode="HTML",
        )


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("clan:"))
async def process_clan_choice(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    clan_id = int(callback_query.data.split(":")[1])

    user = db.users.find_one({"user_id": user_id})

    if user and user.get("clan_id"):
        await callback_query.answer("You already have a clan!", show_alert=True)
        return

    db.users.update_one(
        {"user_id": user_id},
        {"$set": {"clan_id": clan_id}}
    )
    db.clans.update_one(
        {"id": clan_id},
        {"$inc": {"members_count": 1}}
    )

    clan = db.clans.find_one({"id": clan_id})
    clan_name = clan["name"] if clan else f"Clan {clan_id}"

    await callback_query.message.edit_text(
        f"🎉 Welcome to <b>{clan_name}</b>!\n\n"
        "Your focus now contributes to your circle.\n"
        "Use /clan to see circle info!",
        parse_mode="HTML",
    )
    await callback_query.answer()


@dp.message_handler(commands=["clan_top", "clans"])
async def cmd_clan_top(message: types.Message):
    clans = list(db.clans.find().sort("total_protein", -1).limit(10))

    if not clans:
        await message.answer("No clans yet.")
        return

    text = ["💫 <b>PRIVATE CIRCLES LEADERBOARD</b>\n"]
    medals = ["🥇", "🥈", "🥉"]

    for i, clan in enumerate(clans, start=1):
        name = clan.get("name", f"Clan {clan.get('id')}")
        protein = clan.get("total_protein", 0)
        members = clan.get("members_count", 0)
        medal = medals[i - 1] if i <= 3 else f"{i}."
        text.append(f"{medal} <b>{name}</b>")
        text.append(f"   🧬 {protein:,} attention | 👥 {members} members\n")

    await message.answer("\n".join(text), parse_mode="HTML")


# ============================
# START COMMAND
# ============================


@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args()

    # Ensure user is registered in database
    existing_user = db.users.find_one({"user_id": user_id})
    is_new_user = existing_user is None
    
    if is_new_user:
        # Register new user with default values
        db.users.insert_one({
            "user_id": user_id,
            "protein": 0,
            "energy": MAX_ENERGY,
            "xp": 0,
            "level": 1,
            "last_daily": None,
            "daily_streak": 0,
            "clan_id": None,
            "clan_contribution": 0,
            "referrer_id": None,
            "referral_count": 0
        })
        # Also initialize stats
        db.stats.insert_one({
            "user_id": user_id,
            "total_clicks": 0,
            "rare_drops": 0,
            "best_combo": 0
        })
        # Refresh existing_user after insert
        existing_user = db.users.find_one({"user_id": user_id})
    
    if args and args.startswith("ref"):
        try:
            referrer_id = int(args[3:])
            if referrer_id != user_id:
                # Check if user already has a referrer (can only be referred once)
                if existing_user is None or existing_user.get("referrer_id") is None:
                    # Give friend their welcome protein bonus
                    db.users.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "protein": REFERRAL_FRIEND_BONUS_PROTEIN,
                                "referrer_id": referrer_id
                            }
                        },
                        upsert=True
                    )
                    # Track referral pair
                    db.referrals.update_one(
                        {"referrer_id": referrer_id, "referred_id": user_id},
                        {"$set": {"referrer_id": referrer_id, "referred_id": user_id}},
                        upsert=True
                    )
                    
                    # Update referrer's stats
                    referrer = db.users.find_one({"user_id": referrer_id})
                    new_protein = (referrer.get("protein", 0) if referrer else 0) + REFERRAL_REFERRER_BONUS_PROTEIN
                    current_energy = referrer.get("energy", MAX_ENERGY) if referrer else MAX_ENERGY
                    new_energy = min(MAX_ENERGY, current_energy + REFERRAL_REFERRER_BONUS_ENERGY)
                    new_ref_count = (referrer.get("referral_count", 0) if referrer else 0) + 1
                    
                    db.users.update_one(
                        {"user_id": referrer_id},
                        {
                            "$set": {
                                "protein": new_protein,
                                "energy": new_energy,
                                "referral_count": new_ref_count
                            }
                        },
                        upsert=True
                    )

                    # Keep in-memory snapshot in sync if referrer is active
                    if referrer_id in user_data:
                        ref_user = get_user(referrer_id)
                        ref_user["balance"] += REFERRAL_REFERRER_BONUS_PROTEIN
                        ref_user["energy"] = min(
                            MAX_ENERGY,
                            ref_user.get("energy", MAX_ENERGY) + REFERRAL_REFERRER_BONUS_ENERGY,
                        )

                    # Auto-add as friends
                    try:
                        db.friendships.update_one(
                            {"user_id": referrer_id, "friend_id": user_id},
                            {"$set": {"user_id": referrer_id, "friend_id": user_id}},
                            upsert=True
                        )
                    except Exception:
                        pass

                    try:
                        updated_referrer = db.users.find_one({"user_id": referrer_id})
                        ref_count = updated_referrer.get("referral_count", 0) if updated_referrer else 0
                        await bot.send_message(
                            referrer_id,
                            f"🎉 New referral! +{REFERRAL_REFERRER_BONUS_PROTEIN} attention and +{REFERRAL_REFERRER_BONUS_ENERGY} desire!\n"
                            f"Total referrals: {ref_count}",
                        )
                    except Exception:
                        pass

                    await message.answer(
                        "🎁 Welcome! You got +100 attention bonus from referral!\nStart focusing now! 💎",
                        parse_mode="HTML",
                    )
        except Exception:
            pass

    get_user(user_id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

    webapp = InlineKeyboardMarkup(row_width=1)
    webapp.add(
        InlineKeyboardButton(
            "🎮 PLAY GAME",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    )
    await message.answer(
        "■ <b>Cigdem</b>\n\n🎮 Tap button to enter.",
        reply_markup=webapp,
        parse_mode="HTML",
    )
    await message.answer("Or use buttons below:", reply_markup=keyboard)


# ============================
# OTHER COMMANDS
# ============================


@dp.message_handler(commands=["profile"])
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    user = db.users.find_one({"user_id": user_id})

    if user is None:
        await message.answer("You have no profile yet. Tap 💎 Focus to begin.")
        return

    protein = user.get("protein", 0)
    energy = user.get("energy", MAX_ENERGY)
    xp = user.get("xp", 0)
    level = user.get("level", 1)
    last_daily = user.get("last_daily")
    daily_streak = user.get("daily_streak", 0)
    stats = get_or_create_stats(user_id)

    text_lines = [
        f"👤 Profile of <b>{message.from_user.full_name}</b>",
        "",
        f"🧬 Attention: <b>{protein}</b>",
        f"⭐ Trust Level: <b>{level}</b>",
        f"📈 Trust: <b>{xp}</b>",
        f"⚡ Desire: <b>{energy}/{MAX_ENERGY}</b>",
        "",
        f"🖱 Total focus: <b>{stats['total_clicks']}</b>",
        f"🌟 Rare moments: <b>{stats['rare_drops']}</b>",
        f"🔥 Best streak: <b>{stats['best_combo']}</b>",
    ]

    if last_daily:
        text_lines.append("")
        text_lines.append(f"🎁 Daily streak: <b>{daily_streak}</b>")

    await message.answer("\n".join(text_lines), parse_mode="HTML")


@dp.message_handler(commands=["daily"])
async def cmd_daily(message: types.Message):
    user_id = message.from_user.id
    user = db.users.find_one({"user_id": user_id})

    if user is None:
        db.users.insert_one({"user_id": user_id})
        balance = 0
        last_daily = None
        daily_streak = 0
    else:
        balance = user.get("protein", 0)
        last_daily = user.get("last_daily")
        daily_streak = user.get("daily_streak", 0)

    now = datetime.utcnow().date()

    if last_daily is not None:
        try:
            last_date = datetime.fromisoformat(last_daily).date()
        except ValueError:
            last_date = None
    else:
        last_date = None

    if last_date == now:
        await message.answer(
            "🕒 You already claimed your daily reward today. Come back tomorrow!"
        )
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
        "🎁 <b>DAILY ATTENTION</b>\n"
        f"+<b>{reward}</b> attention\n\n"
        f"🔥 Streak: <b>{daily_streak}</b> day(s)\n"
        "She'll remember tomorrow."
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
        await message.answer(
            f"⚡ Boost already active!\nRemaining: {minutes} min {seconds} sec."
        )
        return

    if user["balance"] < BOOST_COST:
        await message.answer(
            f"Not enough attention for boost.\nNeed: {BOOST_COST}, you have: {user['balance']}."
        )
        return

    user["balance"] -= BOOST_COST
    user["boost_until"] = now + BOOST_DURATION
    save_user_to_db(user_id, user)

    await message.answer(
        f"⚡ BOOST X{BOOST_MULTIPLIER} ACTIVATED!\n"
        f"Duration: {BOOST_DURATION // 60} minutes.\n"
        f"Cost: {BOOST_COST} attention."
    )


@dp.message_handler(lambda m: m.text == BTN_BOOST)
async def btn_boost(message: types.Message):
    await cmd_boost(message)


@dp.message_handler(commands=["upgrade"])
async def cmd_upgrade(message: types.Message):
    text = (
        "🧬 <b>UPGRADES MENU</b>\n\n"
        "1️⃣ <b>+1 Min Gain</b> — 200 attention (/upgrade_min)\n"
        "2️⃣ <b>+1 Max Gain</b> — 300 attention (/upgrade_max)\n\n"
        "Choose an upgrade."
    )
    await message.answer(text, parse_mode="HTML")


@dp.message_handler(commands=["upgrade_min"])
async def upgrade_min(message: types.Message):
    user = get_user(message.from_user.id)
    cost = 200

    if user["balance"] < cost:
        return await message.answer("Not enough attention for this upgrade.")

    user["balance"] -= cost
    user["min_gain"] += 1
    await message.answer(
        f"🔧 Min focus increased! Now: {user['min_gain']}–{user['max_gain']} ATTENTION."
    )


@dp.message_handler(commands=["upgrade_max"])
async def upgrade_max(message: types.Message):
    user = get_user(message.from_user.id)
    cost = 300

    if user["balance"] < cost:
        return await message.answer("Not enough attention for this upgrade.")

    user["balance"] -= cost
    user["max_gain"] += 1
    await message.answer(
        f"🔧 Max focus increased! Now: {user['min_gain']}–{user['max_gain']} ATTENTION."
    )


@dp.message_handler(lambda m: m.text == BTN_MINE)
async def mine(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    regenerate_energy(user)

    if user["energy"] <= 0:
        await message.answer("⚡ Desire is empty!\nShe needs a pause…")
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
        levelup_text = "\n🔥 TRUST LEVEL UP!"
    else:
        levelup_text = ""

    save_user_to_db(user_id, user)

    # Update clan contribution
    user = db.users.find_one({"user_id": user_id})
    if user and user.get("clan_id"):
        clan_id = user["clan_id"]
        db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"clan_contribution": gained}}
        )
        db.clans.update_one(
            {"id": clan_id},
            {"$inc": {"total_protein": gained}}
        )

    if rarity == "LEGENDARY":
        msg = (
            f"{'=' * 30}\n"
            f"💎💎💎 LEGENDARY ATTENTION! 💎💎💎\n"
            f"{'=' * 30}\n"
            f"+{gained} ATTENTION (x{multiplier})\n"
            "🎉 SHE NOTICED! 🎉\n"
        )
    elif rarity == "EPIC":
        msg = (
            f"{'=' * 25}\n"
            f"🔮🔮 EPIC ATTENTION! 🔮🔮\n"
            f"{'=' * 25}\n"
            f"+{gained} ATTENTION (x{multiplier})\n"
            "⚡ RARE MOMENT!\n"
        )
    elif rarity == "RARE":
        msg = f"⭐ RARE ATTENTION!\n+{gained} ATTENTION (x{multiplier})\n"
    else:
        msg = f"{emoji} +{gained} ATTENTION\n"

    msg += (
        f"{boost_text}\n"
        f"💰 Attention: {user['balance']}\n"
        f"📊 Trust: {user['xp']}\n"
        f"⭐ Trust Level: {user['level']}\n"
        f"⚡ Desire: {user['energy']}/{MAX_ENERGY}{levelup_text}"
    )
    await message.answer(msg)


@dp.message_handler(commands=["top"])
async def cmd_top(message: types.Message):
    users = list(db.users.find().sort("protein", -1).limit(20))

    if not users:
        await message.answer("Leaderboard is empty.")
        return

    text = ["👁️ <b>WHO SHE NOTICES TODAY</b>\n"]

    for i, user_doc in enumerate(users, start=1):
        uid = user_doc["user_id"]
        protein = user_doc.get("protein", 0)
        try:
            user_chat = await bot.get_chat(uid)
            name = user_chat.full_name
        except Exception:
            name = f"User {uid}"
        text.append(f"{i}. ■ <b>{name}</b> — {protein} ATT")

    await message.answer("\n".join(text), parse_mode="HTML")


def run_bot():
    """
    Start the Telegram bot polling.
    Separated into a function so it can be started from another module (e.g. main.py).
    """
    print("Cigdem ■ bot is running with ALL FEATURES...")
    executor.start_polling(dp, skip_updates=True)


if __name__ == "__main__":
    run_bot()


