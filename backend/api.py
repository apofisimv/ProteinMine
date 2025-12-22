from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import time
import math

from dotenv import load_dotenv
from .db import db

app = Flask(__name__)
CORS(app)

# Resolve paths in a way that works both on local (Windows) and server (Linux)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

# Load environment variables from a .env file at the project root (ProteinMine/.env)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

MAX_ENERGY = 50
# Energy regenerates 1 point every 72 seconds = full recovery in 1 hour (3600 seconds / 50 energy)
ENERGY_REGEN_TIME = 72

# Database is initialized in db.py


# Approximate coordinates of main Turkish cities / provinces
TURKEY_CITIES = {
    "Istanbul": (41.015137, 28.97953),
    "Ankara": (39.9334, 32.8597),
    "Izmir": (38.4237, 27.1428),
    "Bursa": (40.1950, 29.0600),
    "Antalya": (36.8969, 30.7133),
    "Adana": (37.0, 35.3213),
    "Konya": (37.8746, 32.4932),
    "Gaziantep": (37.0662, 37.3833),
    "Kayseri": (38.7225, 35.4875),
    "Mersin": (36.8121, 34.6415),
    "Diyarbakır": (37.9144, 40.2306),
    "Samsun": (41.2867, 36.33),
    "Trabzon": (41.0015, 39.7178),
    "Erzurum": (39.9043, 41.2679),
    "Eskişehir": (39.7667, 30.5256),
    "Sakarya": (40.7569, 30.3781),
    "Kocaeli": (40.8533, 29.8815),
    "Malatya": (38.3552, 38.3095),
    "Şanlıurfa": (37.1591, 38.7969),
}

# Rough radius (km) to still count as being "from" a given Turkish city
CITY_RADIUS_KM = 120.0


def haversine_km(lat1, lon1, lat2, lon2):
    """
    Compute approximate distance (km) between 2 lat/lng points.
    """
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def detect_turkey_city(lat, lng):
    """
    Map raw GPS coords to nearest Turkish city (province) name.
    Only returns a city if distance is within CITY_RADIUS_KM.
    """
    if lat is None or lng is None:
        return None

    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return None

    best_city = None
    best_dist = None

    for city_name, (c_lat, c_lng) in TURKEY_CITIES.items():
        dist = haversine_km(lat, lng, c_lat, c_lng)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_city = city_name

    if best_city is not None and best_dist is not None and best_dist <= CITY_RADIUS_KM:
        return best_city

    return None


@app.route("/", methods=["GET"])
def index():
    """
    Serve the Telegram WebApp frontend (ProteinMine/frontend/index.html)
    from the same origin as the API so that /api/* calls work behind a
    single ngrok tunnel (Option 1 setup).
    Injects environment variables into the HTML.
    """
    html_path = os.path.join(FRONTEND_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    
    # Inject Telegram link from environment variable
    telegram_link = os.getenv("TELEGRAM_LINK", "https://t.me/CigdemCrystal1")
    html_content = html_content.replace(
        'href="https://t.me/CigdemCrystal1"',
        f'href="{telegram_link}"'
    )
    
    # Inject background images from environment variables
    gate_screen_2_bg = os.getenv("GATE_SCREEN_2_BG_IMAGE", "")
    gate_screen_3_bg = os.getenv("GATE_SCREEN_3_BG_IMAGE", "")
    chigdem_photo_url = os.getenv("CHIGDEM_PHOTO_URL", "")
    mine_background_image = os.getenv("MINE_BACKGROUND_IMAGE", "")
    
    html_content = html_content.replace("{{GATE_SCREEN_2_BG_IMAGE}}", gate_screen_2_bg)
    html_content = html_content.replace("{{GATE_SCREEN_3_BG_IMAGE}}", gate_screen_3_bg)
    html_content = html_content.replace("{{CHIGDEM_PHOTO_URL}}", chigdem_photo_url)
    html_content = html_content.replace("{{MINE_BACKGROUND_IMAGE}}", mine_background_image)
    
    from flask import Response
    return Response(html_content, mimetype="text/html")

@app.route("/api/user/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = db.users.find_one({"user_id": user_id})
    
    # Auto-create a user if it doesn't exist yet (first time from WebApp)
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
            "referral_count": 0,
            "last_energy_ts": time.time()
        }
        db.users.insert_one(user)
        protein, energy, xp, level = 0, MAX_ENERGY, 0, 1
    else:
        protein = user.get("protein", 0)
        energy = user.get("energy", MAX_ENERGY)
        xp = user.get("xp", 0)
        level = user.get("level", 1)
        
        # Regenerate energy based on time elapsed
        last_energy_ts = user.get("last_energy_ts", time.time())
        now = time.time()
        elapsed = now - last_energy_ts
        regen_points = int(elapsed // ENERGY_REGEN_TIME)
        
        if regen_points > 0:
            energy = min(MAX_ENERGY, energy + regen_points)
            # Update energy and timestamp in database
            db.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "energy": energy,
                        "last_energy_ts": now
                    }
                }
            )

    return jsonify(
        {
            "protein": protein,
            "energy": energy,
            "xp": xp,
            "level": level,
            "maxEnergy": MAX_ENERGY,
        }
    )


@app.route("/api/referral/<int:user_id>", methods=["GET"])
def get_referral_link(user_id):
    """
    Return a shareable referral link for the given Telegram user id.
    Uses TELEGRAM_BOT_USERNAME from environment.
    """
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME")
    if not bot_username:
        return jsonify({"error": "TELEGRAM_BOT_USERNAME is not configured"}), 500

    ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    return jsonify({"referral_link": ref_link})


@app.route("/api/user-track", methods=["POST"])
def user_track():
    """
    Track a single snapshot from the WebApp:
    - telegramId, username, first/last name
    - lat/lng (optional)
    - current points in the web mini-game

    Frontend JS sends POST /api/user-track with this payload.
    We store one row per Telegram user and update it on every call.
    """
    data = request.get_json(silent=True) or {}

    telegram_id = data.get("telegramId")
    username = data.get("username")
    first_name = data.get("firstName")
    last_name = data.get("lastName")
    points = data.get("points") or 0
    lat = data.get("lat")
    lng = data.get("lng")
    photo_url = data.get("photoUrl")

    try:
        if telegram_id is not None:
            telegram_id = int(telegram_id)
    except (TypeError, ValueError):
        telegram_id = None

    try:
        points = int(points)
    except (TypeError, ValueError):
        points = 0

    # If no Telegram id we still accept, but it won't be user-unique
    # (rare in real Telegram WebApp usage).
    city = detect_turkey_city(lat, lng)
    now_ts = int(time.time())

    # Upsert by telegram_id; if it is NULL we just insert a new row each time
    if telegram_id is not None:
        db.user_track.update_one(
            {"telegram_id": telegram_id},
            {
                "$set": {
                    "telegram_id": telegram_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "city": city,
                    "lat": float(lat) if lat is not None else None,
                    "lng": float(lng) if lng is not None else None,
                    "points": points,
                    "last_seen": now_ts,
                    "photo_url": photo_url
                }
            },
            upsert=True
        )
    else:
        # Insert new document without telegram_id
        db.user_track.insert_one({
            "telegram_id": None,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "city": city,
            "lat": float(lat) if lat is not None else None,
            "lng": float(lng) if lng is not None else None,
            "points": points,
            "last_seen": now_ts,
            "photo_url": photo_url
        })

    return jsonify(
        {
            "ok": True,
            "city": city,
            "points": points,
        }
    )


@app.route("/api/mine/<int:user_id>", methods=["POST"])
def mine(user_id):
    user = db.users.find_one({"user_id": user_id})
    
    # Auto-create user if they don't exist yet (first time mining from WebApp)
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
            "referral_count": 0,
            "last_energy_ts": time.time()
        }
        db.users.insert_one(user)
        protein, energy, xp, level = 0, MAX_ENERGY, 0, 1
    else:
        protein = user.get("protein", 0)
        energy = user.get("energy", MAX_ENERGY)
        xp = user.get("xp", 0)
        level = user.get("level", 1)
        
        # Regenerate energy based on time elapsed before mining
        last_energy_ts = user.get("last_energy_ts", time.time())
        now = time.time()
        elapsed = now - last_energy_ts
        regen_points = int(elapsed // ENERGY_REGEN_TIME)
        
        if regen_points > 0:
            energy = min(MAX_ENERGY, energy + regen_points)

    if energy <= 0:
        return jsonify({"error": "No energy"}), 400

    import random

    roll = random.random()

    if roll < 0.002:
        rarity = "LEGENDARY"
        multiplier = 100
        emoji = "💎"
    elif roll < 0.02:
        rarity = "EPIC"
        multiplier = 20
        emoji = "🔮"
    elif roll < 0.20:
        rarity = "RARE"
        multiplier = 5
        emoji = "⭐"
    else:
        rarity = "COMMON"
        multiplier = 1
        emoji = "🧬"

    base_gain = random.randint(1, 5)
    gained = base_gain * multiplier

    energy -= 1
    protein += gained
    xp += gained

    levelup = False
    if xp >= level * 100:
        level += 1
        xp = 0
        levelup = True

    # Update energy and timestamp when energy is consumed
    now = time.time()
    db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "protein": protein,
                "energy": energy,
                "xp": xp,
                "level": level,
                "last_energy_ts": now
            }
        }
    )

    # Update clan contribution
    if user.get("clan_id"):
        clan_id = user["clan_id"]
        db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"clan_contribution": gained}}
        )
        db.clans.update_one(
            {"id": clan_id},
            {"$inc": {"total_protein": gained}}
        )

    return jsonify(
        {
            "success": True,
            "rarity": rarity,
            "emoji": emoji,
            "multiplier": multiplier,
            "gained": gained,
            "protein": protein,
            "energy": energy,
            "xp": xp,
            "level": level,
            "levelup": levelup,
        }
    )


@app.route("/api/turkey-stats", methods=["GET"])
def turkey_stats():
    """
    Aggregate city statistics for the Turkey map.

    Response shape:
    {
      "cityStats": [
        {"name": "Istanbul", "points": 12345, "users": 10},
        ...
      ]
    }
    """
    # Use MongoDB aggregation pipeline
    pipeline = [
        {"$match": {"city": {"$ne": None, "$ne": ""}}},
        {
            "$group": {
                "_id": "$city",
                "users": {"$sum": 1},
                "total_points": {"$sum": "$points"}
            }
        },
        {"$sort": {"total_points": -1}}
    ]

    results = db.user_track.aggregate(pipeline)

    city_stats = []
    for result in results:
        city_name = result["_id"]
        users = result.get("users", 0)
        total_points = result.get("total_points", 0)
        if not city_name:
            continue
        city_stats.append(
            {
                "name": city_name,
                "points": int(total_points),
                "users": int(users),
            }
        )

    return jsonify({"cityStats": city_stats})


@app.route("/api/clans", methods=["GET"])
def get_clans():
    clans_docs = list(db.clans.find().sort("total_protein", -1))

    clans = []
    for clan in clans_docs:
        clans.append(
            {
                "id": clan.get("id"),
                "name": clan.get("name", ""),
                "total_protein": clan.get("total_protein", 0),
                "members_count": clan.get("members_count", 0),
            }
        )

    return jsonify(clans)


@app.route("/api/leaderboard/global", methods=["GET"])
def get_global_leaderboard():
    # Get top users sorted by protein
    users = list(db.users.find().sort("protein", -1).limit(50))

    # Get user_track data for these users
    user_ids = [u["user_id"] for u in users]
    user_tracks = {
        track["telegram_id"]: track
        for track in db.user_track.find({"telegram_id": {"$in": user_ids}})
    }

    leaderboard = []
    for user in users:
        user_id = user["user_id"]
        track = user_tracks.get(user_id, {})
        leaderboard.append(
            {
                "user_id": user_id,
                "protein": user.get("protein", 0),
                "level": user.get("level", 1),
                "xp": user.get("xp", 0),
                "username": track.get("username"),
                "avatar_url": track.get("photo_url"),
            }
        )

    return jsonify(leaderboard)


@app.route("/api/leaderboard/friends/<int:user_id>", methods=["GET"])
def get_friends_leaderboard(user_id):
    # Get friend IDs
    friendships = list(db.friendships.find({"user_id": user_id}).limit(20))
    friend_ids = [f["friend_id"] for f in friendships]

    if not friend_ids:
        return jsonify([])

    # Get users data
    users = list(db.users.find({"user_id": {"$in": friend_ids}}).sort("protein", -1).limit(20))

    # Get user_track data
    user_tracks = {
        track["telegram_id"]: track
        for track in db.user_track.find({"telegram_id": {"$in": friend_ids}})
    }

    friends = []
    for user in users:
        user_id_friend = user["user_id"]
        track = user_tracks.get(user_id_friend, {})
        friends.append(
            {
                "user_id": user_id_friend,
                "protein": user.get("protein", 0),
                "level": user.get("level", 1),
                "xp": user.get("xp", 0),
                "username": track.get("username"),
                "avatar_url": track.get("photo_url"),
            }
        )

    return jsonify(friends)


@app.route("/api/user/position/<int:user_id>", methods=["GET"])
def get_user_position(user_id):
    user = db.users.find_one({"user_id": user_id})
    
    if user is None:
        # If user doesn't exist, count all users + 1
        total_users = db.users.count_documents({})
        return jsonify({"position": total_users + 1})
    
    user_protein = user.get("protein", 0)
    
    # Count users with more protein + 1
    position = db.users.count_documents({"protein": {"$gt": user_protein}}) + 1

    return jsonify({"position": position})


def run_api():
   
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    run_api()


